import os
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


def extract_text_to_markdown(pdf_path, start_page, end_page):
    """
    Extract text from PDF and convert to markdown format.

    Args:
        pdf_path: Path to the PDF file
        start_page: Starting page number (1-indexed)
        end_page: Ending page number (1-indexed)

    Returns:
        Markdown formatted text
    """
    markdown_content = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)

            # Validate page range
            if start_page < 1 or end_page > total_pages or start_page > end_page:
                raise ValueError(f"Invalid page range. PDF has {total_pages} pages.")

            # Extract text from specified page range
            for page_num in range(start_page - 1, end_page):
                page = pdf.pages[page_num]
                text = page.extract_text()

                if text:
                    # Add page header
                    markdown_content.append(f"## Page {page_num + 1}\n")

                    # Process text into markdown-friendly format
                    lines = text.split('\n')
                    for line in lines:
                        line = line.strip()
                        if line:
                            markdown_content.append(line + '\n')

                    markdown_content.append('\n---\n\n')  # Page separator

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

        # Extract and convert to markdown
        markdown_text = extract_text_to_markdown(filepath, start_page, end_page)

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
