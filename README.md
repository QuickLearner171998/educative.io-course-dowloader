# Educative Course Downloader

Complete content capture using full-page screenshots.

## Setup

```bash
pip install --break-system-packages -r requirements.txt
python3 -m playwright install chromium
```

Configure `.env`:
```
EDUCATIVE_EMAIL=your@email.com
EDUCATIVE_PASSWORD=yourpassword
```

## Usage

Edit `COURSE_URL` in `quick_start.py`, then run:
```bash
python3 quick_start.py
```

## Method

**Full-page screenshots → PDF** (most reliable)
- Captures 100% of content
- No missing images at page end
- Handles lazy-loading automatically
- Parallel downloads (5 at once)

## Output Structure

```
output/
└── course-name/
    ├── 001_Lesson_Name/
    │   └── Lesson_Name.pdf
    ├── 002_Next_Lesson/
    └── course-name_COMPLETE.pdf
```
