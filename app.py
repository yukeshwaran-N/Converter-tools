import json
import os
import re
import ssl
import uuid
import subprocess
from PIL import Image
import requests
import yt_dlp
from flask import Flask, jsonify, render_template, request, send_file, abort
from werkzeug.utils import secure_filename
import requests
from bs4 import BeautifulSoup
import urllib3
from urllib3.util.ssl_ import create_urllib3_context
app = Flask(__name__)

# Configuration
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['DOWNLOAD_FOLDER'] = 'downloads'
app.config['ALLOWED_IMAGE_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'webp'}
app.config['ALLOWED_VIDEO_EXTENSIONS'] = {'mp4', 'mov', 'avi'}
app.config['TERABOX_COOKIE'] = (
    "ndus=YfXyHg7teHuixlNvmpauAzOJVLLMpf6Ln7EFUmmt; "
    "__stripe_mid=63f057b4-e933-4398-88be-430cc79157f6d3ee1e; "
    "__stripe_sid=05b262a1-6e3c-483c-b032-0f9cdaffcf433dc8fd"
)
# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ctx = create_urllib3_context()
ctx.load_default_certs()

def allowed_image_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_IMAGE_EXTENSIONS']

def allowed_video_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_VIDEO_EXTENSIONS']

def cleanup_files(file_paths):
    """Clean up temporary files"""
    for file_path in file_paths:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            app.logger.error(f"Error deleting file {file_path}: {e}")

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/image-pdf', methods=['GET'])
def image_pdf():
    return render_template('image_pdf.html')

@app.route('/mp4-mp3', methods=['GET'])
def mp4_mp3():
    return render_template('mp4_mp3.html')

@app.route('/youtube-downloader', methods=['GET'])
def youtube_downloader():
    return render_template('youtube_downloader.html')

@app.route('/convert/image-pdf', methods=['POST'])
def convert_image_pdf():
    if 'images[]' not in request.files:
        return jsonify({'error': 'No files uploaded'}), 400
        
    images = request.files.getlist('images[]')
    if not images or all(image.filename == '' for image in images):
        return jsonify({'error': 'No selected files'}), 400

    image_paths = []
    try:
        # Save all images first
        for image in images:
            if not allowed_image_file(image.filename):
                return jsonify({'error': 'Invalid file type'}), 400
                
            filename = secure_filename(image.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image.save(path)
            image_paths.append(path)

        # Convert to PDF
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4().hex}.pdf")
        
        # Using PIL to create PDF
        images_pil = []
        for img_path in image_paths:
            try:
                img = Image.open(img_path).convert('RGB')
                images_pil.append(img)
            except Exception as e:
                cleanup_files(image_paths)
                return jsonify({'error': f'Invalid image file: {str(e)}'}), 400

        if not images_pil:
            return jsonify({'error': 'No valid images to convert'}), 400

        # Save first image as PDF and append others
        images_pil[0].save(pdf_path, save_all=True, append_images=images_pil[1:])

        # Cleanup original images
        cleanup_files(image_paths)

        return send_file(
            pdf_path,
            as_attachment=True,
            download_name='converted.pdf',
            mimetype='application/pdf'
        )

    except Exception as e:
        cleanup_files(image_paths)
        if 'pdf_path' in locals() and os.path.exists(pdf_path):
            cleanup_files([pdf_path])
        return jsonify({'error': str(e)}), 500
@app.route('/convert/mp4-mp3', methods=['POST'])
def convert_mp4_mp3():
    if 'video' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
        
    video = request.files['video']
    if video.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if not allowed_video_file(video.filename):
        return jsonify({'error': 'Invalid file type'}), 400

    input_path = None
    try:
        filename = secure_filename(video.filename)
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        video.save(input_path)

        output_filename = filename.rsplit('.', 1)[0] + ".mp3"
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)

        # Convert using ffmpeg
        result = subprocess.run(
            ['ffmpeg', '-i', input_path, '-vn', '-ab', '192k', '-ar', '44100', '-y', output_path],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            cleanup_files([input_path])
            return jsonify({
                'error': 'Conversion failed',
                'details': result.stderr
            }), 500

        cleanup_files([input_path])
        return send_file(
            output_path,
            as_attachment=True,
            download_name=output_filename,
            mimetype='audio/mpeg'
        )

    except Exception as e:
        if input_path and os.path.exists(input_path):
            cleanup_files([input_path])
        return jsonify({'error': str(e)}), 500

@app.route('/get-video-info', methods=['POST'])
def get_video_info():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'No URL provided'}), 400

    video_url = data['url'].strip()
    if not video_url:
        return jsonify({'error': 'Empty URL provided'}), 400

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            # Extract available formats
            formats = []
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none':  # Only video formats
                    resolution = f.get('height', 0) or 0  # Default to 0 if None
                    formats.append({
                        'format_id': f['format_id'],
                        'resolution': f'{resolution}p',
                        'ext': f['ext'],
                        'filesize': f.get('filesize'),
                        'note': f.get('format_note', '')
                    })
            
            # Remove duplicates and sort by resolution
            unique_formats = {}
            for f in formats:
                res = f['resolution']
                if res not in unique_formats or (f['filesize'] or 0) > (unique_formats[res]['filesize'] or 0):
                    unique_formats[res] = f
            
            # Sort formats by resolution (handle None cases)
            sorted_formats = sorted(
                unique_formats.values(),
                key=lambda x: int(x['resolution'].replace('p', '')) if x['resolution'].replace('p', '').isdigit() else 0
            )

            return jsonify({
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'formats': sorted_formats
            })

    except yt_dlp.utils.DownloadError as e:
        return jsonify({'error': f'YouTube error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download-youtube', methods=['POST'])
def download_youtube():
    data = request.get_json()
    if not data or 'url' not in data or 'format_id' not in data:
        return jsonify({'error': 'Missing parameters'}), 400

    try:
        unique_id = uuid.uuid4().hex
        filename = f"{unique_id}.mp4"
        output_path = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)

        # Updated yt-dlp options to ensure audio is included
        ydl_opts = {
            'format': f'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'restrictfilenames': True,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'postprocessor_args': ['-ar', '44100'],  # Standard audio sample rate
            'extractaudio': False,  # Keep audio
            'keepvideo': True,      # Keep video
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(data['url'], download=True)
            if not info:
                return jsonify({'error': 'Failed to extract video info'}), 500

            # Verify the downloaded file has audio
            check_audio = subprocess.run(
                ['ffprobe', '-i', output_path, '-show_streams', '-select_streams', 'a', '-loglevel', 'error'],
                capture_output=True,
                text=True
            )
            
            if check_audio.returncode != 0:
                cleanup_files([output_path])
                return jsonify({'error': 'Downloaded file has no audio stream'}), 500

        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"{info.get('title', 'video')}.mp4",
            mimetype='video/mp4'
        )

    except yt_dlp.utils.DownloadError as e:
        return jsonify({'error': f'YouTube download error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            if 'output_path' in locals() and os.path.exists(output_path):
                os.remove(output_path)
        except Exception as e:
            app.logger.error(f"Error cleaning up YouTube download: {e}")
@app.route('/terabox-downloader')
def terabox_downloader():
    return render_template('terabox_downloader.html')

@app.route('/get-terabox-info', methods=['POST'])
def get_terabox_info():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'No URL provided'}), 400

    try:
        url = data['url'].strip()
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Cookie': app.config['TERABOX_COOKIE'],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.terabox.com/'
        }

        session = requests.Session()
        session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))

        # URL normalization
        if 'teraboxapp.com' in url:
            url = url.replace('teraboxapp.com', 'terabox.com')
            
        domains = [
            'www.terabox.com',
            'www.terabox.app',
            'terabox.com',
            'www.1024terabox.com'
        ]

        video_info = None
        
        for domain in domains:
            try:
                parsed_url = url.replace('terabox.app', domain).replace('terabox.com', domain)
                response = session.get(
                    parsed_url,
                    headers=headers,
                    timeout=15,
                    verify=False,
                    allow_redirects=True
                )
                
                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')
                title = soup.find('title').text.replace(' - Terabox', '').strip()
                video_url = None

                # Method 1: Check meta tags
                meta_video = soup.find('meta', property='og:video')
                if meta_video and meta_video.get('content'):
                    video_url = meta_video['content']
                
                # Method 2: Check video tag
                if not video_url:
                    video_tag = soup.find('video')
                    if video_tag and video_tag.get('src'):
                        video_url = video_tag['src']

                # Method 3: Check JavaScript variables
                if not video_url:
                    for script in soup.find_all('script'):
                        script_text = script.string
                        if script_text and 'play_url' in script_text:
                            matches = re.findall(r'"play_url":"(https?:\\/\\/[^"]+)"', script_text)
                            if matches:
                                video_url = matches[0].replace('\\/', '/')
                                break

                # Method 4: Check JSON-LD data
                if not video_url:
                    json_ld = soup.find('script', type='application/ld+json')
                    if json_ld:
                        try:
                            ld_data = json.loads(json_ld.string)
                            if isinstance(ld_data, list):
                                ld_data = ld_data[0]
                            video_url = ld_data.get('contentUrl') or ld_data.get('url', '')
                        except json.JSONDecodeError:
                            pass

                # Method 5: Check direct download button
                if not video_url:
                    download_button = soup.find('a', {'class': 'download-btn'})
                    if download_button and download_button.get('href'):
                        video_url = download_button['href']

                if video_url:
                    # Fix URL encoding
                    video_url = video_url.replace('\\u0026', '&')
                    video_info = {
                        'title': title,
                        'video_url': video_url,
                        'thumbnail': soup.find('meta', property='og:image')['content'] if soup.find('meta', property='og:image') else '',
                        'domain': domain
                    }
                    break

            except Exception as e:
                continue

        if not video_info:
            return jsonify({
                'error': 'Failed to extract video information',
                'possible_reasons': [
                    'Invalid or expired cookies',
                    'Video link is private/removed',
                    'Terabox changed their page structure'
                ],
                'solution': 'Refresh cookies or try a different link'
            }), 400

        return jsonify(video_info)

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/download-terabox', methods=['POST'])
def download_terabox():
    data = request.get_json()
    if not data or 'video_url' not in data:
        return jsonify({'error': 'Missing video URL'}), 400

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Cookie': app.config['TERABOX_COOKIE'],
            'Referer': data.get('domain', 'https://www.terabox.com/')
        }

        response = requests.get(
            data['video_url'],
            headers=headers,
            stream=True,
            verify=False,
            timeout=30
        )
        response.raise_for_status()

        filename = f"terabox_{uuid.uuid4().hex}.mp4"
        filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        return send_file(
            filepath,
            as_attachment=True,
            download_name=f"{data.get('title', 'terabox_video')}.mp4",
            mimetype='video/mp4'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'filepath' in locals() and os.path.exists(filepath):
            os.remove(filepath)

if __name__ == '__main__':
    app.run(debug=True)