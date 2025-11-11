# PDF to Markdown Extractor

A web application that extracts text from PDF documents and converts it to markdown format with page range selection support.

## Features

- Upload PDF files via drag-and-drop or file selection
- Extract text from specific page ranges
- Convert extracted text to markdown format
- Live preview of extracted markdown
- Copy to clipboard functionality
- Download extracted markdown as .md file
- Clean, modern user interface
- Automatic page numbering and separation

## Tech Stack

**Backend:**
- Python 3.x
- Flask (web framework)
- pdfplumber (PDF text extraction)
- flask-cors (CORS support)

**Frontend:**
- HTML5/CSS3/JavaScript
- Marked.js (markdown preview)
- Responsive design

## Installation

### Prerequisites

- Python 3.7 or higher
- pip (Python package manager)

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd markdown-extractor
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python app.py
```

4. Open your browser and navigate to:
```
http://localhost:5000
```

## Usage

1. **Upload PDF**: Click the upload area or drag and drop a PDF file
2. **Select Page Range**:
   - Enter the start page number (default: 1)
   - Enter the end page number (default: last page)
   - The total page count is displayed automatically
3. **Extract**: Click the "Extract Markdown" button
4. **View Results**:
   - View raw markdown in the "Markdown" tab
   - See formatted preview in the "Preview" tab
5. **Export**:
   - Copy to clipboard using the "Copy" button
   - Download as .md file using the "Download" button

## API Endpoints

### POST `/api/extract`

Extracts text from a PDF file and converts it to markdown.

**Request:**
- Method: POST
- Content-Type: multipart/form-data
- Body:
  - `file`: PDF file (required)
  - `start_page`: Starting page number (optional, default: 1)
  - `end_page`: Ending page number (optional, default: last page)

**Response:**
```json
{
  "success": true,
  "markdown": "# Extracted markdown content...",
  "pages_extracted": "1-5",
  "total_pages": 10
}
```

### GET `/api/health`

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "message": "PDF to Markdown Extractor API is running"
}
```

## Project Structure

```
markdown-extractor/
├── app.py                  # Flask backend application
├── requirements.txt        # Python dependencies
├── frontend/              # Frontend files
│   ├── index.html        # Main HTML page
│   ├── style.css         # Styles
│   └── script.js         # JavaScript logic
├── uploads/              # Temporary upload folder (auto-created)
├── .gitignore           # Git ignore rules
└── README.md            # This file
```

## Configuration

You can modify the following settings in `app.py`:

- `MAX_FILE_SIZE`: Maximum upload file size (default: 16MB)
- `UPLOAD_FOLDER`: Temporary upload directory (default: 'uploads')
- `port`: Server port (default: 5000)

## Development

To run in development mode with auto-reload:

```bash
python app.py
```

The Flask development server will start with debug mode enabled.

## Security Notes

- Uploaded PDF files are automatically deleted after processing
- File type validation ensures only PDF files are accepted
- Maximum file size limit prevents resource exhaustion
- Secure filename handling prevents directory traversal attacks

## Limitations

- Maximum file size: 16MB (configurable)
- Text extraction quality depends on PDF format
- Scanned PDFs (images) require OCR (not currently supported)
- Complex PDF layouts may have formatting issues

## Future Enhancements

- OCR support for scanned PDFs
- Multiple file batch processing
- Custom markdown formatting options
- PDF metadata extraction
- Export to other formats (HTML, TXT, etc.)
- User authentication and file management

## License

See LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.