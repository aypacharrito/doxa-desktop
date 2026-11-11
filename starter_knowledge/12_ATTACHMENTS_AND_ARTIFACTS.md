# Attachments and artifact production

An attachment feature is a pipeline, not just a file picker:

1. Let the owner choose files explicitly.
2. Copy or reference them with stable identifiers and metadata.
3. Detect format, size, and supported extraction method.
4. Extract text or structure without modifying the original.
5. Chunk and index large content for retrieval.
6. Preserve source path, filename, page or section location, and import time.
7. Show unsupported, encrypted, corrupted, or oversized files clearly.

Common inputs include text, Markdown, source code, JSON, CSV, PDF, DOCX, XLSX, PPTX, images, and audio. Each type needs a dedicated adapter; changing a filename extension does not convert the content.

## Generated deliverables

Generated files should be written to an owned output directory. Use atomic writes when practical and do not overwrite an existing deliverable without explicit intent. Validate the artifact after creation:

- source code compiles or its tests pass;
- JSON parses;
- CSV rows and columns are consistent;
- Office or PDF files open and contain expected sections;
- archives contain the intended paths and exclude runtime secrets;
- images and audio can be decoded.

Return the final absolute path, file type, size, and verification summary. Keep intermediate working files separate from deliverables.

## Image understanding

Text-only local language models cannot inspect pixels directly. Image support requires an OCR or vision model adapter. Store extracted text and visual metadata while retaining the original image reference. Never claim to have seen visual details when only a filename or OCR text was available.

