// State management
let selectedFile = null;
let totalPages = 0;
let extractedMarkdown = '';

// DOM elements
const pdfFileInput = document.getElementById('pdfFile');
const uploadBox = document.getElementById('uploadBox');
const uploadText = document.getElementById('uploadText');
const fileInfo = document.getElementById('fileInfo');
const pageRangeSection = document.getElementById('pageRangeSection');
const totalPagesText = document.getElementById('totalPages');
const startPageInput = document.getElementById('startPage');
const endPageInput = document.getElementById('endPage');
const extractBtn = document.getElementById('extractBtn');
const loading = document.getElementById('loading');
const errorMessage = document.getElementById('errorMessage');
const resultSection = document.getElementById('resultSection');
const markdownOutput = document.getElementById('markdownOutput');
const markdownPreview = document.getElementById('markdownPreview');
const copyBtn = document.getElementById('copyBtn');
const downloadBtn = document.getElementById('downloadBtn');
const resetBtn = document.getElementById('resetBtn');

// Event listeners
pdfFileInput.addEventListener('change', handleFileSelect);
extractBtn.addEventListener('click', handleExtract);
copyBtn.addEventListener('click', handleCopy);
downloadBtn.addEventListener('click', handleDownload);
resetBtn.addEventListener('click', handleReset);

// Drag and drop functionality
uploadBox.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadBox.classList.add('drag-over');
});

uploadBox.addEventListener('dragleave', () => {
    uploadBox.classList.remove('drag-over');
});

uploadBox.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadBox.classList.remove('drag-over');

    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0].type === 'application/pdf') {
        pdfFileInput.files = files;
        handleFileSelect({ target: pdfFileInput });
    } else {
        showError('Please drop a valid PDF file');
    }
});

// Tab switching
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const tabName = btn.dataset.tab;
        switchTab(tabName);
    });
});

function handleFileSelect(event) {
    const file = event.target.files[0];

    if (!file) {
        return;
    }

    if (file.type !== 'application/pdf') {
        showError('Please select a valid PDF file');
        return;
    }

    selectedFile = file;
    uploadText.textContent = 'PDF Selected';
    fileInfo.textContent = `${file.name} (${formatFileSize(file.size)})`;

    // Get total pages using a quick API call
    getTotalPages(file);
}

async function getTotalPages(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('start_page', '1');
    formData.append('end_page', '1');

    try {
        const response = await fetch('/api/extract', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.total_pages) {
            totalPages = data.total_pages;
            endPageInput.value = totalPages;
            endPageInput.max = totalPages;
            startPageInput.max = totalPages;
            totalPagesText.textContent = `Total pages in PDF: ${totalPages}`;
            pageRangeSection.style.display = 'block';
        }
    } catch (error) {
        console.error('Error getting total pages:', error);
        // Show page range section anyway
        pageRangeSection.style.display = 'block';
    }
}

async function handleExtract() {
    if (!selectedFile) {
        showError('Please select a PDF file first');
        return;
    }

    const startPage = parseInt(startPageInput.value) || 1;
    const endPage = parseInt(endPageInput.value) || totalPages;

    if (startPage < 1 || endPage < 1) {
        showError('Page numbers must be greater than 0');
        return;
    }

    if (startPage > endPage) {
        showError('Start page must be less than or equal to end page');
        return;
    }

    hideError();
    showLoading();
    resultSection.style.display = 'none';

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('start_page', startPage);
    formData.append('end_page', endPage);

    try {
        const response = await fetch('/api/extract', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        hideLoading();

        if (response.ok && data.success) {
            extractedMarkdown = data.markdown;
            displayResults(data);
        } else {
            showError(data.error || 'An error occurred during extraction');
        }
    } catch (error) {
        hideLoading();
        showError('Failed to connect to the server. Please try again.');
        console.error('Error:', error);
    }
}

function displayResults(data) {
    markdownOutput.textContent = data.markdown;
    markdownPreview.innerHTML = marked.parse(data.markdown);
    resultSection.style.display = 'block';
    switchTab('markdown');

    // Scroll to results
    resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function handleCopy() {
    navigator.clipboard.writeText(extractedMarkdown).then(() => {
        const originalText = copyBtn.textContent;
        copyBtn.textContent = 'Copied!';
        copyBtn.style.background = 'var(--success-color)';

        setTimeout(() => {
            copyBtn.textContent = originalText;
            copyBtn.style.background = '';
        }, 2000);
    }).catch(err => {
        showError('Failed to copy to clipboard');
        console.error('Copy error:', err);
    });
}

function handleDownload() {
    const blob = new Blob([extractedMarkdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${selectedFile.name.replace('.pdf', '')}-extracted.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function handleReset() {
    selectedFile = null;
    totalPages = 0;
    extractedMarkdown = '';
    pdfFileInput.value = '';
    uploadText.textContent = 'Choose PDF or drag and drop';
    fileInfo.textContent = '';
    startPageInput.value = '1';
    endPageInput.value = '';
    pageRangeSection.style.display = 'none';
    resultSection.style.display = 'none';
    hideError();
}

function switchTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });

    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    document.getElementById(`${tabName}Tab`).classList.add('active');
}

function showLoading() {
    loading.style.display = 'block';
    extractBtn.disabled = true;
}

function hideLoading() {
    loading.style.display = 'none';
    extractBtn.disabled = false;
}

function showError(message) {
    errorMessage.textContent = message;
    errorMessage.style.display = 'block';
    setTimeout(() => {
        hideError();
    }, 5000);
}

function hideError() {
    errorMessage.style.display = 'none';
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}
