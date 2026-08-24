# Plix Icon Editor

> **Asset Notice:** Some visual assets in this repository belong to PLIX and/or their respective rights holders. Their inclusion does not grant permission for redistribution or commercial reuse. Please see the Intellectual Property & Usage Notice below.

> This repository is shared primarily as a technical portfolio/project reference. PLIX-owned visual assets remain proprietary and should not be reused without authorization.

A web-based icon customization and management tool built for fast product-design workflows.

The application allows users to search, preview, customize, upload, manage, and download PNG icon assets through a simple interface. It uses Flask and Pillow for image processing, Supabase for cloud storage and icon metadata, and Render for deployment.

## Features

- Search icons by name, filename, tags, and detected colors
- Preview icons before downloading
- Resize PNG icons
- Remove image backgrounds
- Change background colors
- Download customized PNG assets
- Upload new icons through the browser
- Edit icon names and search tags
- Remove icons without modifying the source code
- Automatic dominant color detection
- Password-protected icon management
- Supabase Storage for uploaded assets
- Supabase PostgreSQL for icon metadata
- Direct Supabase CDN thumbnail loading
- Paginated icon gallery designed to support 500+ icons
- Database-side full-text search
- Local icon fallback if Supabase is unavailable

## Tech Stack

### Backend
- Python
- Flask
- Pillow (PIL)
- Gunicorn

### Frontend
- HTML5
- CSS3
- Vanilla JavaScript
- Fetch API

### Database & Storage
- Supabase PostgreSQL
- Supabase Storage
- PostgreSQL Full-Text Search
- GIN Search Index

### Deployment & Development
- Render
- Git
- GitHub
- Codex
- Python unittest

## Architecture

```text
                     Browser
                        |
               HTML + CSS + JavaScript
                        |
                     Flask API
                    /         \
                   /           \
                  v             v
        Supabase Database     Pillow
        metadata + search     image processing
                  |
                  v
          Supabase Storage
             PNG Assets
                  |
                  v
          Supabase CDN
           thumbnails

## Intellectual Property & Usage Notice

The icon assets, illustrations, visual elements, product-related graphics, and other brand-specific creative materials included in or referenced by this project are the property of **PLIX / its respective rights holders**.

These assets are included only for the purpose of demonstrating and maintaining this internal design-tool workflow.

### Important

- The PLIX icons and brand assets are **not owned by the repository author**.
- Do not copy, redistribute, resell, republish, modify, or commercially use PLIX-owned assets without appropriate authorization.
- Do not treat the inclusion of these assets in this repository as a grant of license, ownership, or permission for independent use.
- Any use of PLIX trademarks, logos, icons, illustrations, product graphics, or other proprietary material should follow PLIX's internal brand guidelines and applicable intellectual-property rights.
- If you fork, clone, reuse, or adapt this project's source code, remove or replace PLIX-owned visual assets unless you have permission to use them.
- The source code of this project and the ownership rights of the included brand assets should be treated separately.

Please use all PLIX-owned materials carefully and preserve the rights of PLIX and any other applicable rights holders.
