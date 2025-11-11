import os
import re
import pdfplumber
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
try:
    from markitdown import MarkItDown
    MARKITDOWN_AVAILABLE = True
except ImportError:
    MARKITDOWN_AVAILABLE = False

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered
    MARKER_AVAILABLE = True
    # Load models once at startup
    print("Loading Marker models... (this may take a moment on first run)")
    MARKER_MODELS = create_model_dict()
    MARKER_CONVERTER = PdfConverter(artifact_dict=MARKER_MODELS)
    print("✓ Marker models loaded successfully!")
except ImportError as e:
    print(f"✗ Marker not available: Import error - {e}")
    MARKER_AVAILABLE = False
    MARKER_MODELS = None
    MARKER_CONVERTER = None
except Exception as e:
    print(f"✗ Marker models failed to load: {e}")
    MARKER_AVAILABLE = False
    MARKER_MODELS = None
    MARKER_CONVERTER = None

app = Flask(__name__, static_folder='frontend')
CORS(app)

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    """Check if the uploaded file has a valid extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def clean_text(text):
    """Clean and normalize extracted text."""
    # Remove excessive whitespace
    text = re.sub(r'[ \t]+', ' ', text)

    # Remove word breaks (hyphenation at line end) - handle both \n and space
    # Examples: "Play- ing" -> "Playing", "dun-\ngeon" -> "dungeon"
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)  # With newline
    text = re.sub(r'(\w)-\s+(\w)', r'\1\2', text)  # With spaces only

    # Fix broken words across lines (e.g., "experi ence" -> "experience")
    # Look for lowercase letter followed by newline/space and lowercase letter
    text = re.sub(r'([a-z])\s*\n\s*([a-z])', r'\1\2', text)

    # Normalize multiple spaces
    text = re.sub(r'  +', ' ', text)

    # Normalize line breaks (but keep single line breaks)
    text = re.sub(r'\n\n+', '\n\n', text)

    return text.strip()


def detect_heading(line, next_line=None):
    """Detect if a line is likely a heading."""
    line = line.strip()

    # Empty lines are not headings
    if not line:
        return False

    # All caps lines (at least 3 chars) are likely headings
    if len(line) >= 3 and line.isupper() and not line.endswith('.'):
        return True

    # Short lines (< 60 chars) followed by empty line might be headings
    if len(line) < 60 and next_line is not None and not next_line.strip():
        # Check if it starts with capital and doesn't end with common punctuation
        if line[0].isupper() and not line.endswith((',', ';', ':')):
            return True

    return False


def format_line_as_markdown(line, is_heading=False, heading_level=3):
    """Format a line as markdown."""
    line = line.strip()

    if not line:
        return ''

    # Detect and format bullet points
    if re.match(r'^[•\-\*]\s+', line):
        # Normalize bullet to markdown format
        line = re.sub(r'^[•\-\*]\s+', '- ', line)
        return line

    # Detect numbered lists
    if re.match(r'^\d+[\.\)]\s+', line):
        return line

    # Format as heading if detected
    if is_heading:
        return f"{'#' * heading_level} {line}"

    return line


def extract_text_with_layout(page):
    """
    Extract text from a page with better layout awareness.
    Handles multi-column layouts by detecting columns and reading them in order.
    """
    try:
        # Extract words with their positions
        words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)

        if not words:
            # Fallback to basic extraction
            return page.extract_text()

        # Get page dimensions
        page_width = page.width
        page_height = page.height

        # Detect column boundaries FIRST by analyzing x-coordinate distribution
        # Find the largest horizontal gap that could separate columns
        all_x_positions = sorted(set([int(w['x0']) for w in words] + [int(w['x1']) for w in words]))

        # Find gaps between consecutive x-positions
        gaps = []
        for i in range(len(all_x_positions) - 1):
            gap_size = all_x_positions[i + 1] - all_x_positions[i]
            if gap_size > 40:  # Significant gap
                gap_center = (all_x_positions[i] + all_x_positions[i + 1]) / 2
                # Only consider gaps in the middle region of the page
                if page_width * 0.25 < gap_center < page_width * 0.75:
                    gaps.append((gap_size, gap_center))

        # Determine column boundaries
        if gaps:
            # Sort by gap size and take the largest
            gaps.sort(reverse=True)
            column_gap = gaps[0][1]  # Take the center of the largest gap

            # Two column layout
            column_boundaries = [
                (0, column_gap, 0),  # Left column
                (column_gap, page_width, 1)  # Right column
            ]
        else:
            # Single column
            column_boundaries = [(0, page_width, 0)]

        # Assign each word to a column based on its x-position
        for word in words:
            word_center_x = (word['x0'] + word['x1']) / 2

            assigned = False
            for min_x, max_x, col_idx in column_boundaries:
                if min_x <= word_center_x <= max_x:
                    word['column'] = col_idx
                    assigned = True
                    break

            if not assigned:
                # Fallback: assign to nearest column
                distances = [(abs(word_center_x - (min_x + max_x) / 2), col_idx) for min_x, max_x, col_idx in column_boundaries]
                word['column'] = min(distances)[1]

        # Process each column separately
        result_lines = []

        for col_idx in range(len(column_boundaries)):
            # Get all words in this column
            column_words = [w for w in words if w.get('column') == col_idx]

            if not column_words:
                continue

            # Sort words in this column by y-position, then x-position
            column_words.sort(key=lambda w: (w['top'], w['x0']))

            # Group words into lines within this column
            lines_in_column = []
            current_line_words = []
            last_top = None
            y_tolerance = 5  # Tolerance for considering words on the same line

            for word in column_words:
                if last_top is None or abs(word['top'] - last_top) <= y_tolerance:
                    # Same line
                    current_line_words.append(word)
                    if last_top is None:
                        last_top = word['top']
                else:
                    # New line
                    if current_line_words:
                        line_text = ' '.join([w['text'] for w in current_line_words])
                        lines_in_column.append((current_line_words[0]['top'], line_text))
                    current_line_words = [word]
                    last_top = word['top']

            # Add last line
            if current_line_words:
                line_text = ' '.join([w['text'] for w in current_line_words])
                lines_in_column.append((current_line_words[0]['top'], line_text))

            # Sort lines by y-position and add to result
            lines_in_column.sort(key=lambda x: x[0])
            result_lines.extend([line_text for _, line_text in lines_in_column])

        return '\n'.join(result_lines)

    except Exception as e:
        # Fallback to layout-preserving extraction
        try:
            text = page.extract_text(layout=True, x_tolerance=3, y_tolerance=3)
            if text:
                return text
        except:
            pass

        # Final fallback
        return page.extract_text() or ""


def is_list_item(line):
    """Check if a line is a list item."""
    line = line.strip()
    if not line:
        return False

    # Check for bullet points
    if re.match(r'^[•\-\*]\s+', line):
        return True

    # Check for numbered lists
    if re.match(r'^\d+[\.\)]\s+', line):
        return True

    return False


def extract_with_markitdown(pdf_path):
    """
    Extract text from PDF using MarkItDown library.
    This provides better column detection and structure preservation.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Markdown formatted text
    """
    if not MARKITDOWN_AVAILABLE:
        raise ImportError("MarkItDown library not available")

    md = MarkItDown()
    result = md.convert(pdf_path)
    return result.text_content


def extract_with_marker(pdf_path, start_page, end_page):
    """
    Extract text from PDF using Marker library.
    Marker uses computer vision and ML for superior layout detection,
    especially for multi-column documents.

    Args:
        pdf_path: Path to the PDF file
        start_page: Starting page number (1-indexed)
        end_page: Ending page number (1-indexed)

    Returns:
        Markdown formatted text
    """
    if not MARKER_AVAILABLE or not MARKER_CONVERTER:
        raise ImportError("Marker library not available")

    # Marker processes the whole PDF
    rendered = MARKER_CONVERTER(pdf_path)
    full_text, _, images = text_from_rendered(rendered)

    # If we need a page range, we'll need to filter the output
    # For now, return the full extraction
    # TODO: Implement page range filtering for Marker output
    return full_text


def extract_with_pymupdf(pdf_path, start_page, end_page):
    """
    Extract text from PDF using PyMuPDF (fitz).
    PyMuPDF has excellent column detection and reading order.

    Args:
        pdf_path: Path to the PDF file
        start_page: Starting page number (1-indexed)
        end_page: Ending page number (1-indexed)

    Returns:
        Markdown formatted text
    """
    if not PYMUPDF_AVAILABLE:
        raise ImportError("PyMuPDF library not available")

    doc = fitz.open(pdf_path)
    markdown_content = []

    try:
        for page_num in range(start_page - 1, end_page):
            if page_num >= len(doc):
                break

            page = doc[page_num]

            # Get text blocks with position info - PyMuPDF sorts these in reading order
            # This handles multi-column layouts automatically
            blocks = page.get_text("blocks")

            markdown_content.append(f"## Page {page_num + 1}\n\n")

            for block in blocks:
                # block is a tuple: (x0, y0, x1, y1, text, block_no, block_type)
                if len(block) >= 5:
                    text = block[4].strip()
                    if text:
                        # Add text with proper spacing
                        markdown_content.append(text + '\n\n')

            markdown_content.append('\n---\n\n')

        return ''.join(markdown_content)

    finally:
        doc.close()


def extract_text_to_markdown(pdf_path, start_page, end_page, options=None):
    """
    Extract text from PDF and convert to markdown format.

    Args:
        pdf_path: Path to the PDF file
        start_page: Starting page number (1-indexed)
        end_page: Ending page number (1-indexed)
        options: Dictionary of formatting options

    Returns:
        Markdown formatted text
    """
    if options is None:
        options = {}

    use_marker = options.get('use_marker', True)
    use_pymupdf = options.get('use_pymupdf', False)
    use_markitdown = options.get('use_markitdown', False)
    include_page_numbers = options.get('include_page_numbers', True)
    include_page_breaks = options.get('include_page_breaks', True)
    filter_headers_footers = options.get('filter_headers_footers', True)
    preserve_formatting = options.get('preserve_formatting', True)

    # Try Marker first - it has the best column detection using CV/ML
    if use_marker and MARKER_AVAILABLE:
        try:
            print("Attempting extraction with Marker...")
            result = extract_with_marker(pdf_path, start_page, end_page)
            print("Marker extraction successful!")
            return result
        except Exception as e:
            # Fall back to other methods if Marker fails
            print(f"Marker failed with error: {e}")
            import traceback
            traceback.print_exc()

    # Try PyMuPDF second
    if use_pymupdf and PYMUPDF_AVAILABLE:
        try:
            print("Attempting extraction with PyMuPDF...")
            result = extract_with_pymupdf(pdf_path, start_page, end_page)
            print("PyMuPDF extraction successful!")
            return result
        except Exception as e:
            # Fall back to other methods if PyMuPDF fails
            print(f"PyMuPDF failed with error: {e}")

    # Try MarkItDown if available and requested
    if use_markitdown and MARKITDOWN_AVAILABLE:
        try:
            print("Attempting extraction with MarkItDown...")
            full_text = extract_with_markitdown(pdf_path)

            # If page range is not full document, we need to extract specific pages
            # For now, return full document - MarkItDown doesn't support page ranges natively
            # TODO: Implement page range filtering for MarkItDown output
            if start_page == 1:
                with pdfplumber.open(pdf_path) as pdf:
                    total_pages = len(pdf.pages)
                    if end_page >= total_pages:
                        return full_text

            # Fall through to pdfplumber for page range extraction
        except Exception as e:
            # Fall back to pdfplumber if MarkItDown fails
            print(f"MarkItDown failed with error: {e}")

    print("Falling back to pdfplumber extraction...")
    markdown_content = []
    common_footers = set()  # Track repeated text that might be footers

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)

            # Validate page range
            if start_page < 1 or end_page > total_pages or start_page > end_page:
                raise ValueError(f"Invalid page range. PDF has {total_pages} pages.")

            # First pass: collect potential headers/footers
            if filter_headers_footers:
                page_last_lines = []
                for page_num in range(start_page - 1, end_page):
                    text = pdf.pages[page_num].extract_text()
                    if text:
                        lines = text.split('\n')
                        if lines:
                            # Check last few lines for common footers
                            page_last_lines.extend([l.strip() for l in lines[-3:] if l.strip()])

                # Find lines that appear multiple times (likely footers)
                from collections import Counter
                line_counts = Counter(page_last_lines)
                common_footers = {line for line, count in line_counts.items() if count > 2 and len(line) < 100}

            # Second pass: extract and format text
            for page_num in range(start_page - 1, end_page):
                page = pdf.pages[page_num]
                text = extract_text_with_layout(page)

                if text:
                    # Add page header if requested
                    if include_page_numbers:
                        markdown_content.append(f"## Page {page_num + 1}\n\n")

                    # Clean text
                    text = clean_text(text)
                    lines = text.split('\n')

                    # Process lines with better list handling
                    i = 0
                    paragraph_buffer = []
                    in_list = False
                    list_buffer = []

                    while i < len(lines):
                        line = lines[i].strip()
                        next_line = lines[i + 1].strip() if i + 1 < len(lines) else None

                        # Skip common footers/headers
                        if filter_headers_footers and line in common_footers:
                            i += 1
                            continue

                        # Skip page numbers at top/bottom
                        if filter_headers_footers and re.match(r'^Page\s+\d+\s*$', line, re.IGNORECASE):
                            i += 1
                            continue

                        if not line:
                            # Empty line - flush buffers
                            if in_list and list_buffer:
                                # Flush list
                                for list_item in list_buffer:
                                    markdown_content.append(list_item + '\n')
                                markdown_content.append('\n')
                                list_buffer = []
                                in_list = False
                            elif paragraph_buffer:
                                # Flush paragraph
                                markdown_content.append(' '.join(paragraph_buffer) + '\n\n')
                                paragraph_buffer = []
                            i += 1
                            continue

                        # Check if this is a heading
                        is_heading_line = detect_heading(line, next_line) if preserve_formatting else False

                        if is_heading_line:
                            # Flush any existing buffers
                            if in_list and list_buffer:
                                for list_item in list_buffer:
                                    markdown_content.append(list_item + '\n')
                                markdown_content.append('\n')
                                list_buffer = []
                                in_list = False
                            if paragraph_buffer:
                                markdown_content.append(' '.join(paragraph_buffer) + '\n\n')
                                paragraph_buffer = []

                            formatted_line = format_line_as_markdown(line, is_heading=True)
                            markdown_content.append(formatted_line + '\n\n')
                            i += 1
                            continue

                        # Check if this is a list item
                        if is_list_item(line):
                            # Flush paragraph buffer if we're starting a list
                            if paragraph_buffer:
                                markdown_content.append(' '.join(paragraph_buffer) + '\n\n')
                                paragraph_buffer = []

                            in_list = True
                            formatted_line = format_line_as_markdown(line)
                            list_buffer.append(formatted_line)
                        elif in_list:
                            # Check if this is a continuation of the previous list item
                            # (indented or doesn't start with list marker)
                            if list_buffer and not is_heading_line:
                                # Append to the last list item
                                list_buffer[-1] += ' ' + line
                            else:
                                # End of list, flush it
                                for list_item in list_buffer:
                                    markdown_content.append(list_item + '\n')
                                markdown_content.append('\n')
                                list_buffer = []
                                in_list = False
                                # Process this line as regular text
                                paragraph_buffer.append(line)
                        else:
                            # Regular text - add to paragraph buffer
                            paragraph_buffer.append(line)

                        i += 1

                    # Flush remaining buffers
                    if in_list and list_buffer:
                        for list_item in list_buffer:
                            markdown_content.append(list_item + '\n')
                        markdown_content.append('\n')
                    if paragraph_buffer:
                        markdown_content.append(' '.join(paragraph_buffer) + '\n\n')

                    # Add page separator if requested
                    if include_page_breaks and page_num < end_page - 1:
                        markdown_content.append('\n---\n\n')

            return ''.join(markdown_content)

    except Exception as e:
        raise Exception(f"Error extracting PDF: {str(e)}")


@app.route('/')
def index():
    """Serve the main HTML page."""
    return send_from_directory('frontend', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    """Serve static files from frontend folder."""
    return send_from_directory('frontend', path)


@app.route('/api/extract', methods=['POST'])
def extract_pdf():
    """
    API endpoint to extract text from PDF and convert to markdown.

    Expected form data:
        - file: PDF file
        - start_page: Starting page number (optional, default: 1)
        - end_page: Ending page number (optional, default: last page)
        - include_page_numbers: Include page headers (optional, default: true)
        - include_page_breaks: Include page separators (optional, default: true)
        - filter_headers_footers: Filter repeated headers/footers (optional, default: true)
        - preserve_formatting: Preserve text formatting (optional, default: true)
    """
    # Check if file is present
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    # Check if filename is empty
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Validate file type
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Only PDF files are allowed.'}), 400

    try:
        # Save uploaded file
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Get page range from request
        start_page = int(request.form.get('start_page', 1))

        # Get total pages to set default end_page
        with pdfplumber.open(filepath) as pdf:
            total_pages = len(pdf.pages)

        end_page = int(request.form.get('end_page', total_pages))

        # Get formatting options
        options = {
            'use_marker': request.form.get('use_marker', 'true').lower() == 'true',
            'use_pymupdf': request.form.get('use_pymupdf', 'false').lower() == 'true',
            'use_markitdown': request.form.get('use_markitdown', 'false').lower() == 'true',
            'include_page_numbers': request.form.get('include_page_numbers', 'true').lower() == 'true',
            'include_page_breaks': request.form.get('include_page_breaks', 'true').lower() == 'true',
            'filter_headers_footers': request.form.get('filter_headers_footers', 'true').lower() == 'true',
            'preserve_formatting': request.form.get('preserve_formatting', 'true').lower() == 'true',
        }

        # Extract and convert to markdown
        markdown_text = extract_text_to_markdown(filepath, start_page, end_page, options)

        # Clean up uploaded file
        os.remove(filepath)

        return jsonify({
            'success': True,
            'markdown': markdown_text,
            'pages_extracted': f"{start_page}-{end_page}",
            'total_pages': total_pages
        })

    except ValueError as e:
        # Clean up file if it exists
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'error': str(e)}), 400

    except Exception as e:
        # Clean up file if it exists
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'message': 'PDF to Markdown Extractor API is running'})


@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file too large error."""
    return jsonify({
        'error': f'File too large. Maximum file size is {MAX_FILE_SIZE // (1024 * 1024)}MB.'
    }), 413


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
