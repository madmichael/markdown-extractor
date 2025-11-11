import os
import re
import pdfplumber
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

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

        # Detect columns by clustering x-coordinates
        x_coords = [w['x0'] for w in words]

        # Simple column detection: find gaps in x-coordinates
        sorted_x = sorted(set(x_coords))
        columns = []
        current_column = [sorted_x[0]]

        # Group x-coordinates into columns (gap > 50 points suggests new column)
        for x in sorted_x[1:]:
            if x - current_column[-1] > 50:
                columns.append(current_column)
                current_column = [x]
            else:
                current_column.append(x)
        columns.append(current_column)

        # If we have multiple columns, sort words by column then by y-position
        if len(columns) > 1:
            # Determine column boundaries
            column_boundaries = []
            for col in columns:
                min_x = min(col)
                max_x = max(col)
                mid_x = (min_x + max_x) / 2
                column_boundaries.append((min_x, max_x, mid_x))

            # Assign each word to a column
            for word in words:
                word_x = (word['x0'] + word['x1']) / 2
                # Find which column this word belongs to
                for col_idx, (min_x, max_x, mid_x) in enumerate(column_boundaries):
                    if min_x <= word_x <= max_x + 20:  # Small tolerance
                        word['column'] = col_idx
                        break
                else:
                    # If no match, assign to nearest column
                    distances = [abs(word_x - mid_x) for _, _, mid_x in column_boundaries]
                    word['column'] = distances.index(min(distances))

            # Sort words: first by column (left to right), then by y-position (top to bottom)
            words.sort(key=lambda w: (w.get('column', 0), w['top'], w['x0']))
        else:
            # Single column: just sort by y-position then x-position
            words.sort(key=lambda w: (w['top'], w['x0']))

        # Reconstruct text with proper line breaks
        lines = []
        current_line = []
        last_top = None
        last_column = None

        for word in words:
            current_top = word['top']
            current_column = word.get('column', 0)

            # Check if we need a new line
            if last_top is not None:
                # New line if y-position changed significantly (>3 points) or column changed
                if abs(current_top - last_top) > 3 or (current_column != last_column and len(columns) > 1):
                    if current_line:
                        lines.append(' '.join(current_line))
                        current_line = []

            current_line.append(word['text'])
            last_top = current_top
            last_column = current_column

        # Add last line
        if current_line:
            lines.append(' '.join(current_line))

        return '\n'.join(lines)

    except Exception as e:
        # Fallback to layout-preserving extraction
        text = page.extract_text(layout=True, x_tolerance=3, y_tolerance=3)
        if not text:
            text = page.extract_text()
        return text


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

    include_page_numbers = options.get('include_page_numbers', True)
    include_page_breaks = options.get('include_page_breaks', True)
    filter_headers_footers = options.get('filter_headers_footers', True)
    preserve_formatting = options.get('preserve_formatting', True)

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
