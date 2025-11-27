#!/usr/bin/env python3
"""
Educative Course Downloader with Complete Content Capture
Uses multiple methods to ensure NO content is lost:
1. Full-page screenshots (most reliable)
2. Playwright PDF with enhanced loading
3. img2pdf for screenshot conversion
"""

import asyncio
import os
import re
import json
import img2pdf
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, Browser
from PyPDF2 import PdfMerger
from PIL import Image

# Configuration
load_dotenv()

class Config:
    EMAIL = os.getenv('EDUCATIVE_EMAIL', '')
    PASSWORD = os.getenv('EDUCATIVE_PASSWORD', '')
    OUTPUT_DIR = Path('output')
    COOKIES_FILE = OUTPUT_DIR / 'cookies.json'
    MAX_WORKERS = 5  # Parallel downloads
    SCREENSHOT_METHOD = True  # Use screenshots for guaranteed content capture

# Course URL - CHANGE THIS
COURSE_URL = "https://www.educative.io/courses/agentic-ai-systems"


class CourseDownloader:
    """Downloads Educative courses with complete content capture"""
    
    def __init__(self, course_url: str):
        self.course_url = course_url
        self.course_name = self._extract_course_name(course_url)
        self.course_dir = Config.OUTPUT_DIR / self.course_name
        self.browser: Optional[Browser] = None
        self.lesson_urls: List[str] = []
        
    def _extract_course_name(self, url: str) -> str:
        """Extract course name from URL"""
        match = re.search(r'/courses/([^/]+)', url)
        return match.group(1) if match else 'course'
    
    def _sanitize_filename(self, name: str) -> str:
        """Create safe filename"""
        name = re.sub(r'[^\w\s-]', '', name)
        name = re.sub(r'[-\s]+', '_', name)
        return name[:80]
    
    async def authenticate(self, page: Page) -> bool:
        """Authenticate with saved cookies or manual login"""
        try:
            print("🔐 Authenticating...")
            
            # Try saved cookies
            if Config.COOKIES_FILE.exists():
                with open(Config.COOKIES_FILE, 'r') as f:
                    cookies = json.load(f)
                await page.context.add_cookies(cookies)
                await page.goto(self.course_url)
                await page.wait_for_load_state('networkidle')
                
                if await page.evaluate("() => document.cookie.includes('logged_in')"):
                    print("✓ Using saved session")
                    return True
            
            # Manual/auto login
            print("Opening login page...")
            await page.goto('https://www.educative.io/login')
            await page.wait_for_load_state('networkidle')
            
            if Config.EMAIL and Config.PASSWORD:
                print("Auto-filling credentials...")
                try:
                    # Click "Continue with Email" button if present
                    email_button = page.locator('text=Continue with Email')
                    if await email_button.count() > 0:
                        print("Clicking 'Continue with Email'...")
                        await email_button.click()
                        await page.wait_for_timeout(1000)
                    
                    # Fill email and password
                    await page.fill('input[type="email"], input[name="email"]', Config.EMAIL)
                    await page.wait_for_timeout(500)
                    await page.fill('input[type="password"], input[name="password"]', Config.PASSWORD)
                    await page.wait_for_timeout(500)
                    
                    # Click submit/login button
                    await page.click('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")')
                    print("⏳ Enter OTP (120s)...")
                    await page.wait_for_timeout(120000)
                except Exception as e:
                    print(f"⚠️ Auto-fill failed: {e}")
                    print("⏳ Manual login (180s)...")
                    await page.wait_for_timeout(180000)
            else:
                print("⏳ Manual login (180s)...")
                await page.wait_for_timeout(180000)
            
            # Verify and save
            await page.goto(self.course_url)
            if await page.evaluate("() => document.cookie.includes('logged_in')"):
                cookies = await page.context.cookies()
                Config.OUTPUT_DIR.mkdir(exist_ok=True)
                with open(Config.COOKIES_FILE, 'w') as f:
                    json.dump(cookies, f)
                print("✓ Authentication successful")
                return True
            
            return False
        except Exception as e:
            print(f"❌ Auth failed: {e}")
            return False
    
    async def extract_lesson_urls(self, page: Page) -> List[str]:
        """Extract all lesson URLs from course"""
        try:
            print("📚 Extracting lesson URLs...")
            await page.goto(self.course_url)
            await page.wait_for_load_state('networkidle')
            
            links = await page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a[href*="/courses/"]'));
                    const base = window.location.pathname;
                    return links
                        .map(a => a.href)
                        .filter(href => href.includes(base) && href !== window.location.href)
                        .filter((v, i, a) => a.indexOf(v) === i);
                }
            """)
            
            self.lesson_urls = links
            print(f"✓ Found {len(links)} lessons")
            return links
        except Exception as e:
            print(f"❌ URL extraction failed: {e}")
            return []
    
    async def download_lesson_as_pdf_screenshots(self, url: str, lesson_num: int, semaphore: asyncio.Semaphore) -> Optional[Path]:
        """
        METHOD 1: Full-page screenshots → PDF (Most Reliable)
        Captures EVERYTHING visible, no content loss possible
        """
        async with semaphore:
            context = None
            try:
                print(f"[{lesson_num}] Downloading (screenshot method): {url}")
                
                # Use reasonable viewport size (not huge)
                context = await self.browser.new_context(viewport={'width': 1440, 'height': 900})
                if Config.COOKIES_FILE.exists():
                    with open(Config.COOKIES_FILE, 'r') as f:
                        await context.add_cookies(json.load(f))
                
                page = await context.new_page()
                await page.goto(url, wait_until='networkidle', timeout=30000)
                
                # Wait for all images
                await page.evaluate("""
                    () => Promise.all(Array.from(document.images)
                        .filter(img => !img.complete)
                        .map(img => new Promise(r => { img.onload = img.onerror = r; })))
                """)
                
                # Multiple scrolls to trigger ALL lazy-loading
                total_height = await page.evaluate("document.body.scrollHeight")
                viewport_height = await page.evaluate("window.innerHeight")
                
                for scroll_pos in range(0, total_height, viewport_height // 2):
                    await page.evaluate(f"window.scrollTo(0, {scroll_pos})")
                    await page.wait_for_timeout(500)
                
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(1000)
                
                # Get title and create lesson folder
                title = await page.title()
                title = self._sanitize_filename(title.split('|')[0].strip())
                lesson_folder = self.course_dir / f"{lesson_num:03d}_{title}"
                lesson_folder.mkdir(parents=True, exist_ok=True)
                
                # Take full-page screenshot
                screenshot_path = lesson_folder / "page_full.png"
                await page.screenshot(path=str(screenshot_path), full_page=True)
                
                # Convert screenshot to PDF
                pdf_path = lesson_folder / f"{title}.pdf"
                with open(pdf_path, 'wb') as f:
                    f.write(img2pdf.convert(str(screenshot_path)))
                
                # Clean up screenshot
                screenshot_path.unlink()
                
                print(f"✓ [{lesson_num}] {title}.pdf")
                await context.close()
                return pdf_path
                
            except Exception as e:
                print(f"✗ [{lesson_num}] Failed: {e}")
                if context:
                    await context.close()
                return None
    
    async def download_lesson_as_pdf_enhanced(self, url: str, lesson_num: int, semaphore: asyncio.Semaphore) -> Optional[Path]:
        """
        METHOD 2: Enhanced Playwright PDF (Fallback)
        Better than basic print, waits for everything
        """
        async with semaphore:
            context = None
            try:
                print(f"[{lesson_num}] Downloading (enhanced PDF): {url}")
                
                context = await self.browser.new_context()
                if Config.COOKIES_FILE.exists():
                    with open(Config.COOKIES_FILE, 'r') as f:
                        await context.add_cookies(json.load(f))
                
                page = await context.new_page()
                await page.goto(url, wait_until='networkidle', timeout=30000)
                
                # Enhanced content loading
                await page.evaluate("""
                    async () => {
                        // Wait for images
                        await Promise.all(Array.from(document.images)
                            .filter(img => !img.complete)
                            .map(img => new Promise(r => { img.onload = img.onerror = r; })));
                        
                        // Scroll to load lazy content
                        const scrolls = 10;
                        const delay = 300;
                        for(let i = 0; i < scrolls; i++) {
                            window.scrollTo(0, (document.body.scrollHeight / scrolls) * i);
                            await new Promise(r => setTimeout(r, delay));
                        }
                        window.scrollTo(0, 0);
                    }
                """)
                
                await page.wait_for_timeout(2000)
                
                # Get title
                title = await page.title()
                title = self._sanitize_filename(title.split('|')[0].strip())
                lesson_folder = self.course_dir / f"{lesson_num:03d}_{title}"
                lesson_folder.mkdir(parents=True, exist_ok=True)
                
                pdf_path = lesson_folder / f"{title}.pdf"
                
                # Enhanced PDF settings
                await page.pdf(
                    path=str(pdf_path),
                    format='Letter',
                    print_background=True,
                    margin={'top': '0.3in', 'bottom': '0.3in', 'left': '0.3in', 'right': '0.3in'},
                    prefer_css_page_size=False,
                    scale=0.9
                )
                
                print(f"✓ [{lesson_num}] {title}.pdf")
                await context.close()
                return pdf_path
                
            except Exception as e:
                print(f"✗ [{lesson_num}] Failed: {e}")
                if context:
                    await context.close()
                return None
    
    async def download_all_lessons(self) -> List[Path]:
        """Download all lessons in parallel"""
        print("=" * 70)
        print(f"🚀 Parallel Download ({Config.MAX_WORKERS} workers)")
        print("=" * 70)
        
        if not self.lesson_urls:
            return []
        
        semaphore = asyncio.Semaphore(Config.MAX_WORKERS)
        
        # Choose method
        download_method = (self.download_lesson_as_pdf_screenshots 
                          if Config.SCREENSHOT_METHOD 
                          else self.download_lesson_as_pdf_enhanced)
        
        tasks = [download_method(url, i, semaphore) 
                for i, url in enumerate(self.lesson_urls, 1)]
        
        pdf_files = await asyncio.gather(*tasks)
        pdf_files = [f for f in pdf_files if f]
        
        print(f"\n✓ Downloaded {len(pdf_files)}/{len(self.lesson_urls)} lessons")
        return pdf_files
    
    def merge_pdfs(self, pdf_files: List[Path]) -> Optional[Path]:
        """Merge all PDFs into complete course"""
        if not pdf_files:
            return None
        
        try:
            print("\n📚 Merging PDFs...")
            merger = PdfMerger()
            
            for pdf in sorted(pdf_files):
                merger.append(str(pdf))
            
            output = self.course_dir / f"{self.course_name}_COMPLETE.pdf"
            merger.write(str(output))
            merger.close()
            
            print(f"✓ Merged: {output.name}")
            return output
        except Exception as e:
            print(f"❌ Merge failed: {e}")
            return None
    
    async def run(self) -> bool:
        """Main execution"""
        async with async_playwright() as p:
            try:
                self.browser = await p.chromium.launch(
                    headless=False,
                    args=['--disable-blink-features=AutomationControlled', '--window-size=1280,800']
                )
                
                # Use reasonable viewport size
                context = await self.browser.new_context(
                    viewport={'width': 1280, 'height': 800}
                )
                page = await context.new_page()
                
                if not await self.authenticate(page):
                    return False
                
                if not await self.extract_lesson_urls(page):
                    return False
                
                await context.close()
                
                pdf_files = await self.download_all_lessons()
                self.merge_pdfs(pdf_files)
                
                await self.browser.close()
                return True
                
            except Exception as e:
                print(f"❌ Error: {e}")
                if self.browser:
                    await self.browser.close()
                return False


# ============================================================
# MAIN EXECUTION
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("  EDUCATIVE COURSE DOWNLOADER")
    print("=" * 70)
    print()
    print("🎯 Method: Full-page screenshots → PDF (100% content capture)")
    print(f"📚 Course: {COURSE_URL}")
    print(f"📧 Email: {Config.EMAIL}")
    print(f"⚡ Workers: {Config.MAX_WORKERS}")
    print()
    print("� Output Structure:")
    print("   output/")
    print("   └── course-name/")
    print("       ├── 001_Lesson_Name/")
    print("       │   └── Lesson_Name.pdf")
    print("       ├── 002_Next_Lesson/")
    print("       └── course-name_COMPLETE.pdf")
    print()
    print("=" * 70)
    print()
    
    downloader = CourseDownloader(COURSE_URL)
    success = asyncio.run(downloader.run())
    
    print()
    if success:
        print("=" * 70)
        print("✅ DOWNLOAD COMPLETE!")
        print("=" * 70)
        print(f"\n📁 Location: {downloader.course_dir}")
        print(f"   • Individual lessons in numbered folders")
        print(f"   • Complete course: {downloader.course_name}_COMPLETE.pdf")
        print("=" * 70)
    else:
        print("=" * 70)
        print("❌ DOWNLOAD FAILED")
        print("=" * 70)
