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
    MAX_WORKERS = 10  # Parallel downloads
    MAX_RETRIES = 5  # Retry attempts for failed downloads
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
        self.cookies: Optional[List] = None  # Store cookies for reuse
        
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
            
            # Try saved cookies - load BEFORE navigation
            if Config.COOKIES_FILE.exists():
                print("Found saved cookies, attempting auto-login...")
                try:
                    with open(Config.COOKIES_FILE, 'r') as f:
                        cookies = json.load(f)
                    
                    # Load cookies into context FIRST
                    await page.context.add_cookies(cookies)
                    
                    # THEN navigate to course URL
                    await page.goto(self.course_url, timeout=90000, wait_until='domcontentloaded')
                    await page.wait_for_timeout(3000)
                    
                    # Check if authentication was successful
                    if await page.evaluate("() => document.cookie.includes('logged_in')"):
                        print("✓ Using saved session")
                        self.cookies = cookies  # Store for parallel downloads
                        return True
                    else:
                        print("⚠️ Saved cookies are invalid or expired")
                except Exception as e:
                    print(f"⚠️ Error loading cookies: {e}")
                    print("Proceeding to manual login...")
            
            # Manual/auto login
            print("Opening login page...")
            try:
                await page.goto('https://www.educative.io/login', timeout=90000, wait_until='domcontentloaded')
                print("✓ Page loaded")
                await page.wait_for_timeout(3000)
                print("✓ Login page ready")
            except Exception as e:
                print(f"⚠️ Page load issue: {e}")
                print("Continuing anyway...")
                await page.wait_for_timeout(3000)
            
            # Manual login only
            print("\n" + "="*70)
            print("⏳ PLEASE COMPLETE THE LOGIN MANUALLY")
            print("   1. Click 'Continue with Email'")
            print("   2. Enter your email and password")  
            print("   3. Complete OTP if required")
            print("   You have 50 seconds...")
            print("="*70 + "\n")
            await page.wait_for_timeout(50000)
            
            # Verify and save
            print("Verifying login...")
            try:
                await page.goto(self.course_url, timeout=90000, wait_until='domcontentloaded')
                await page.wait_for_timeout(3000)
            except Exception as e:
                print(f"⚠️ Navigation to course failed: {e}")
                return False
            
            if await page.evaluate("() => document.cookie.includes('logged_in')"):
                cookies = await page.context.cookies()
                Config.OUTPUT_DIR.mkdir(exist_ok=True)
                with open(Config.COOKIES_FILE, 'w') as f:
                    json.dump(cookies, f)
                print("✓ Authentication successful")
                self.cookies = cookies  # Store for parallel downloads
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
            
            # Click on "Content" tab if it exists (to show TOC)
            try:
                print("   🔍  Looking for Content tab...")
                content_btn = await page.wait_for_selector('text=Content', timeout=5000)
                if content_btn:
                    await content_btn.click()
                    await page.wait_for_timeout(1000)
                    print("   ✓ Clicked Content tab")
            except:
                print("   ℹ️  Content tab not found, continuing...")
            
            # Click "Expand All" to reveal all sub-lessons
            try:
                print("   🔍 Looking for Expand All button...")
                expand_btn = await page.wait_for_selector('text=Expand All', timeout=5000)
                if expand_btn:
                    await expand_btn.click()
                    await page.wait_for_timeout(2000)  # Wait for all chapters to expand
                    print("   ✓ Expanded all chapters")
            except Exception as e:
                print(f"   ⚠️  Could not click Expand All: {e}")
                print("   Continuing anyway...")
            
            # Extract all lesson links using the specific class for lessons
            print("   🔍 Extracting lesson URLs...")
            links = await page.evaluate("""
                () => {
                    // Get all lesson links (including sub-lessons)
                    const lessonLinks = Array.from(document.querySelectorAll('a.Lesson_lesson__uSC7b'));
                    
                    // Extract unique URLs
                    const urls = [...new Set(lessonLinks.map(a => a.href))];
                    
                    // Filter to only include actual lesson pages (not the main course page)
                    const coursePath = window.location.pathname;
                    return urls.filter(url => 
                        url.includes(coursePath) && 
                        url !== window.location.href &&
                        !url.endsWith(coursePath) &&
                        !url.endsWith(coursePath + '/')
                    );
                }
            """)
            
            self.lesson_urls = links
            print(f"✓ Found {len(links)} lessons (including sub-lessons)")
            
            # Show first few for verification
            if links:
                print(f"\n   📝 First few lessons:")
                for url in links[:3]:
                    lesson_name = url.split('/')[-1].replace('-', ' ').title()
                    print(f"      • {lesson_name}")
                if len(links) > 3:
                    print(f"      ... and {len(links) - 3} more\n")
            
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
            # Retry logic
            for attempt in range(1, Config.MAX_RETRIES + 1):
                context = None
                page = None
                try:
                    if attempt > 1:
                        print(f"[{lesson_num}] � Retry attempt {attempt}/{Config.MAX_RETRIES}")
                    else:
                        print(f"[{lesson_num}] �📥 Starting download: {url}")
                    
                    # Use reasonable viewport size (not huge)
                    if attempt == 1:
                        print(f"[{lesson_num}] 🌐 Creating browser context...")
                    context = await self.browser.new_context(viewport={'width': 1440, 'height': 900})
                    
                    # Use stored cookies (no file I/O)
                    if self.cookies:
                        await context.add_cookies(self.cookies)
                        if attempt == 1:
                            print(f"[{lesson_num}] 🍪 Cookies loaded")
                    
                    page = await context.new_page()
                    if attempt == 1:
                        print(f"[{lesson_num}] 🔄 Navigating to page...")
                    await page.goto(url, wait_until='domcontentloaded', timeout=100000)  # 100s
                    
                    # Wait for page to be fully loaded with all resources
                    print(f"[{lesson_num}] ⏳ Waiting for page and resources to load...")
                    await page.wait_for_load_state('load', timeout=100000)  # 100s
                    
                    # Try to wait for networkidle, but don't fail if it times out
                    try:
                        await page.wait_for_load_state('networkidle', timeout=60000)  # 1 minute
                    except:
                        print(f"[{lesson_num}] ⚠️  Network still active (this is OK)")
                    
                    await page.wait_for_timeout(3000)  # Extra 3s for dynamic content
                    print(f"[{lesson_num}] ✓ Page loaded")
                    
                    # Wait for all images with extended timeout
                    print(f"[{lesson_num}] 🖼️  Waiting for images to load...")
                    try:
                        await page.evaluate("""
                            async () => {
                                // Wait for all images to load
                                const images = Array.from(document.images);
                                await Promise.all(
                                    images.map(img => {
                                        if (img.complete) return Promise.resolve();
                                        return new Promise((resolve) => {
                                            img.onload = resolve;
                                            img.onerror = resolve;
                                            // Timeout after 10s per image
                                            setTimeout(resolve, 10000);
                                        });
                                    })
                                );
                            }
                        """)
                        await page.wait_for_timeout(2000)  # Extra 2s buffer
                        print(f"[{lesson_num}] ✓ Images loaded")
                    except Exception as e:
                        print(f"[{lesson_num}] ⚠️  Image loading timeout (continuing anyway): {e}")
                    
                    # Multiple scrolls to trigger ALL lazy-loading with longer waits
                    print(f"[{lesson_num}] 📜 Scrolling to trigger lazy-loaded content...")
                    total_height = await page.evaluate("document.body.scrollHeight")
                    viewport_height = await page.evaluate("window.innerHeight")
                    
                    # Scroll more slowly with longer pauses to trigger lazy loading
                    scroll_step = viewport_height // 3  # Smaller steps
                    for scroll_pos in range(0, total_height, scroll_step):
                        await page.evaluate(f"window.scrollTo(0, {scroll_pos})")
                        await page.wait_for_timeout(1000)  # Increased from 500ms to 1s
                    
                    # Scroll back to top
                    await page.evaluate("window.scrollTo(0, 0)")
                    await page.wait_for_timeout(2000)
                    
                    # Final wait for any remaining lazy-loaded images
                    print(f"[{lesson_num}] ⏳ Final wait for lazy-loaded media...")
                    await page.wait_for_timeout(3000)  # Extended final wait
                    print(f"[{lesson_num}] ✓ Content fully loaded")
                    
                    # Hide minimap if present (to avoid covering content)
                    try:
                        print(f"[{lesson_num}] 🗺️  Checking for minimap...")
                        # Try to find and click the minimap button/toggle
                        minimap_hidden = await page.evaluate("""
                            () => {
                                // Look for common minimap selectors
                                const selectors = [
                                    '[aria-label*="minimap" i]',
                                    '[title*="minimap" i]',
                                    'button[class*="minimap" i]',
                                    '.minimap-toggle',
                                    '[data-testid*="minimap" i]'
                                ];
                                
                                for (const selector of selectors) {
                                    const btn = document.querySelector(selector);
                                    if (btn) {
                                        btn.click();
                                        return true;
                                    }
                                }
                                return false;
                            }
                        """)
                        if minimap_hidden:
                            print(f"[{lesson_num}] ✓ Minimap hidden")
                            await page.wait_for_timeout(500)  # Wait for UI to update
                    except:
                        pass  # Minimap not found or already hidden
                    
                    # Get title and create lesson folder
                    title = await page.title()
                    title = self._sanitize_filename(title.split('|')[0].strip())
                    lesson_folder = self.course_dir / f"{lesson_num:03d}_{title}"
                    lesson_folder.mkdir(parents=True, exist_ok=True)
                    
                    # Take full-page screenshot with increased timeout
                    print(f"[{lesson_num}] 📸 Taking screenshot...")
                    screenshot_path = lesson_folder / "page_full.png"
                    await page.screenshot(path=str(screenshot_path), full_page=True, timeout=60000)  # 60s timeout
                    print(f"[{lesson_num}] ✓ Screenshot saved ({screenshot_path.stat().st_size // 1024} KB)")
                    
                    # Convert screenshot to PDF
                    print(f"[{lesson_num}] 📄 Converting to PDF...")
                    pdf_path = lesson_folder / f"{title}.pdf"
                    with open(pdf_path, 'wb') as f:
                        f.write(img2pdf.convert(str(screenshot_path)))
                    
                    # Clean up screenshot
                    screenshot_path.unlink()
                    
                    pdf_size_kb = pdf_path.stat().st_size // 1024
                    print(f"✅ [{lesson_num}] {title}.pdf ({pdf_size_kb} KB)")
                    print(f"    └─ {pdf_path}")
                    
                    await context.close()
                    return pdf_path
                    
                except Exception as e:
                    error_msg = str(e)
                    
                    # Clean up resources
                    if context:
                        try:
                            await context.close()
                        except:
                            pass
                    
                    # If this is not the last attempt, wait and retry
                    if attempt < Config.MAX_RETRIES:
                        wait_time = attempt * 2  # Exponential backoff: 2s, 4s, 6s
                        print(f"⚠️  [{lesson_num}] Attempt {attempt} failed: {error_msg}")
                        print(f"    └─ Waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
                        continue
                    
                    # Final failure after all retries
                    print(f"❌ [{lesson_num}] FAILED after {Config.MAX_RETRIES} attempts: {error_msg}")
                    print(f"    └─ URL: {url}")
                    
                    # Try to save a debug screenshot
                    try:
                        if page:
                            debug_path = self.course_dir / f"error_lesson_{lesson_num}.png"
                            await page.screenshot(path=str(debug_path))
                            print(f"    └─ Debug screenshot saved: {debug_path}")
                    except:
                        pass
                    
                    return None
            
            return None  # Should never reach here
    
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
                
                # Use stored cookies (no file I/O)
                if self.cookies:
                    await context.add_cookies(self.cookies)
                
                page = await context.new_page()
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                # Wait for page to be fully loaded
                await page.wait_for_load_state('load')
                await page.wait_for_timeout(2000)
                
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
