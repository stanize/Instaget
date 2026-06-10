VERSION = "0.10"

from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
import subprocess
import os
import sys
import glob
import re
import shutil
import json
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ─── OS-AWARE PATHS ────────────────────────────────────────

def get_download_dir():
    if sys.platform == "win32":
        base = os.path.join(os.path.expanduser("~"), "Downloads", "InstaGet")
    else:
        # Android/Termux
        termux_path = os.path.expanduser("~/storage/downloads/InstaGet")
        linux_path = os.path.expanduser("~/Downloads/InstaGet")
        base = termux_path if os.path.exists(os.path.expanduser("~/storage")) else linux_path
    return base

DOWNLOAD_DIR = get_download_dir()
COMPILATIONS_DIR = os.path.join(DOWNLOAD_DIR, "compilations")
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instagram_cookies.txt")
QUEUE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instaget_queue.json")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(COMPILATIONS_DIR, exist_ok=True)

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".mov", ".avi")

w = max(len(DOWNLOAD_DIR), len(QUEUE_FILE), len(sys.platform), 40) + 4
def row(label, value):
    content = f"  {label}: {value}"
    return f"║{content:<{w}}║"
border = "═" * w
print(f"""
╔{border}╗
║{"  InstaGet Server v" + VERSION:^{w}}║
╠{border}╣
{row("Platform ", sys.platform)}
{row("Downloads", DOWNLOAD_DIR)}
{row("Queue    ", QUEUE_FILE)}
╚{border}╝
""")


# ─── QUEUE ─────────────────────────────────────────────────

def load_queue():
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE) as f:
                return json.load(f)
        except:
            return []
    return []


def save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


@app.route("/queue", methods=["GET"])
def get_queue():
    return jsonify(load_queue())


@app.route("/queue/add", methods=["POST"])
def add_to_queue():
    data = request.get_json()
    url = data.get("url", "").strip()
    title = data.get("title", url)
    if not url:
        return jsonify({"error": "No URL"}), 400
    queue = load_queue()
    if any(item["url"] == url for item in queue):
        return jsonify({"status": "exists"})
    queue.append({
        "id": str(len(queue) + 1) + "_" + str(int(datetime.now().timestamp())),
        "url": url,
        "title": title,
        "added": datetime.now().isoformat(),
        "last_status": "queued"
    })
    save_queue(queue)
    return jsonify({"status": "ok"})


@app.route("/queue/remove", methods=["POST"])
def remove_from_queue():
    data = request.get_json()
    item_id = data.get("id", "")
    queue = [item for item in load_queue() if item["id"] != item_id]
    save_queue(queue)
    return jsonify({"status": "ok"})


# ─── PAGE SOURCE EXTRACTOR ─────────────────────────────────

@app.route("/extract-from-source", methods=["POST"])
def extract_from_source():
    """Extract Instagram reel/video URLs from pasted page source HTML."""
    data = request.get_json()
    html = data.get("html", "")
    if not html:
        return jsonify({"error": "No HTML provided"}), 400

    found = set()

    # Match Instagram reel/post/video URLs
    patterns = [
        r'https://www\.instagram\.com/(?:reel|p|tv)/([A-Za-z0-9_\-]+)/?',
        r'"shortcode"\s*:\s*"([A-Za-z0-9_\-]+)"',
        r'"video_url"\s*:\s*"(https://[^"]+\.mp4[^"]*)"',
        r'videoSrc\s*[=:]\s*["\']([^"\']+)["\']',
    ]

    results = []

    # Direct video CDN URLs
    for match in re.finditer(r'https://[a-z0-9\-]+\.cdninstagram\.com/[^\s"\'<>]+\.mp4[^\s"\'<>]*', html):
        url = match.group(0).replace('\\u0026', '&').replace('\\/', '/')
        if url not in found:
            found.add(url)
            results.append({"type": "direct", "url": url, "title": f"Video {len(results)+1}"})

    # Shortcodes -> construct Instagram URLs
    shortcodes = set()
    for pattern in [r'"shortcode"\s*:\s*"([A-Za-z0-9_\-]{5,})"',
                    r'instagram\.com/(?:reel|p)/([A-Za-z0-9_\-]{5,})',
                    r'/reel/([A-Za-z0-9_\-]{5,})/',
                    r'\"code\"\s*:\s*\"([A-Za-z0-9_\-]{5,})\"']:
        for match in re.finditer(pattern, html):
            shortcodes.add(match.group(1))

    for code in shortcodes:
        url = f"https://www.instagram.com/reel/{code}/"
        if url not in found:
            found.add(url)
            results.append({"type": "reel", "url": url, "title": f"Reel {code}"})

    return jsonify({"videos": results, "count": len(results)})


# ─── VERSION ───────────────────────────────────────────────

@app.route("/version")
def version():
    return jsonify({"version": VERSION, "platform": sys.platform, "download_dir": DOWNLOAD_DIR})


# ─── DOWNLOAD ──────────────────────────────────────────────

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url", "").strip()
    queue_id = data.get("queue_id", None)
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    try:
        cmd = [
            "yt-dlp", "--no-playlist", "--socket-timeout", "30",
            "--retries", "3", "--restrict-filenames",
            "-o", os.path.join(DOWNLOAD_DIR, "%(title)s_%(id)s.%(ext)s"),
        ]
        if os.path.exists(COOKIES_FILE):
            cmd += ["--cookies", COOKIES_FILE]
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            if queue_id:
                queue = load_queue()
                for item in queue:
                    if item["id"] == queue_id:
                        item["last_status"] = "downloaded"
                        item["last_downloaded"] = datetime.now().isoformat()
                save_queue(queue)
            return jsonify({"status": "ok"})
        else:
            if queue_id:
                queue = load_queue()
                for item in queue:
                    if item["id"] == queue_id:
                        item["last_status"] = "failed"
                save_queue(queue)
            return jsonify({"error": result.stderr[-500:]}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── VIDEOS ────────────────────────────────────────────────

def get_videos():
    videos = []
    for ext in VIDEO_EXTENSIONS:
        for path in glob.glob(os.path.join(DOWNLOAD_DIR, f"*{ext}")):
            name = os.path.basename(path)
            videos.append({"filename": name, "size": os.path.getsize(path), "mtime": os.path.getmtime(path), "path": path})
    videos.sort(key=lambda v: v["mtime"], reverse=True)
    return videos


def safe_filename(name):
    return re.sub(r"[^\w\-.]", "_", name)


@app.route("/videos", methods=["GET"])
def list_videos():
    return jsonify(get_videos())


@app.route("/video/<path:filename>")
def stream_video(filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    file_size = os.path.getsize(filepath)
    range_header = request.headers.get("Range", None)
    if range_header:
        byte_range = range_header.replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
        length = end - start + 1
        def generate():
            with open(filepath, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining:
                    chunk = f.read(min(8192, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": "video/mp4",
        }
        return Response(generate(), 206, headers=headers)
    return send_file(filepath)


@app.route("/delete", methods=["POST"])
def delete_video():
    data = request.get_json()
    filename = data.get("filename", "")
    folder = data.get("folder", "downloads")
    filepath = os.path.join(COMPILATIONS_DIR if folder == "compilations" else DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    os.remove(filepath)
    return jsonify({"status": "ok"})


@app.route("/move-to-library", methods=["POST"])
def move_to_library():
    data = request.get_json()
    filename = data.get("filename", "")
    src = os.path.join(COMPILATIONS_DIR, filename)
    if not os.path.exists(src):
        return jsonify({"error": "File not found"}), 404
    dst = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(dst):
        base, ext = os.path.splitext(filename)
        dst = os.path.join(DOWNLOAD_DIR, f"{base}_moved{ext}")
    shutil.move(src, dst)
    return jsonify({"status": "ok", "filename": os.path.basename(dst)})


@app.route("/video-duration/<path:filename>")
def video_duration(filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", filepath],
        capture_output=True, text=True
    )
    try:
        return jsonify({"duration": float(result.stdout.strip())})
    except:
        return jsonify({"duration": 0})


@app.route("/rename", methods=["POST"])
def rename_existing():
    renamed = []
    for ext in VIDEO_EXTENSIONS:
        for path in glob.glob(os.path.join(DOWNLOAD_DIR, f"*{ext}")):
            name = os.path.basename(path)
            new_name = safe_filename(name)
            if new_name != name:
                new_path = os.path.join(DOWNLOAD_DIR, new_name)
                os.rename(path, new_path)
                renamed.append(f"{name} -> {new_name}")
    return jsonify({"status": "ok", "renamed": renamed})


# ─── MERGE ─────────────────────────────────────────────────

@app.route("/merge", methods=["POST"])
def merge():
    data = request.get_json()
    clips = data.get("clips", [])
    output_name = re.sub(r"[^\w\-]", "_", data.get("output_name", "compilation").strip())
    if not clips:
        return jsonify({"error": "No clips provided"}), 400
    output_path = os.path.join(COMPILATIONS_DIR, f"{output_name}.mp4")
    temp_files = []
    concat_file = os.path.join(DOWNLOAD_DIR, "_concat.txt")
    try:
        for i, clip in enumerate(clips):
            filepath = os.path.join(DOWNLOAD_DIR, clip["filename"])
            if not os.path.exists(filepath):
                return jsonify({"error": f"File not found: {clip['filename']}"}), 400
            temp_path = os.path.join(DOWNLOAD_DIR, f"_temp_{i}.mp4")
            temp_files.append(temp_path)
            start = float(clip.get("start") or 0)
            end = clip.get("end")
            cmd = ["ffmpeg", "-y"]
            if start:
                cmd += ["-ss", str(start)]
            cmd += ["-i", filepath]
            if end:
                cmd += ["-t", str(float(end) - start)]
            cmd += ["-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", temp_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return jsonify({"error": f"clip {i} failed: {result.stderr[-500:]}"}), 500
        with open(concat_file, "w") as f:
            for tp in temp_files:
                f.write(f"file '{tp}'\n")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return jsonify({"status": "ok", "output": os.path.basename(output_path)})
        else:
            return jsonify({"error": f"concat failed: {result.stderr[-800:]}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        for tp in temp_files:
            if os.path.exists(tp):
                os.remove(tp)
        if os.path.exists(concat_file):
            os.remove(concat_file)


# ─── TRIM ──────────────────────────────────────────────────

@app.route("/trim", methods=["POST"])
def trim_video():
    data = request.get_json()
    filename = data.get("filename", "")
    start = float(data.get("start") or 0)
    end = data.get("end")
    mode = data.get("mode", "copy")
    src = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(src):
        return jsonify({"error": "File not found"}), 404
    base, ext = os.path.splitext(filename)
    if mode == "copy":
        out_name = f"{base}_trimmed{ext}"
        out_path = os.path.join(DOWNLOAD_DIR, out_name)
        counter = 1
        while os.path.exists(out_path):
            out_name = f"{base}_trimmed_{counter}{ext}"
            out_path = os.path.join(DOWNLOAD_DIR, out_name)
            counter += 1
    else:
        out_path = os.path.join(DOWNLOAD_DIR, f"_trimtmp_{filename}")
    cmd = ["ffmpeg", "-y"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", src]
    if end:
        cmd += ["-t", str(float(end) - start)]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", out_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return jsonify({"error": result.stderr[-500:]}), 500
        if mode == "overwrite":
            os.replace(out_path, src)
            out_name = filename
        return jsonify({"status": "ok", "filename": out_name})
    except Exception as e:
        if os.path.exists(out_path):
            os.remove(out_path)
        return jsonify({"error": str(e)}), 500


# ─── COMPILATIONS ──────────────────────────────────────────

@app.route("/compilations/<path:filename>")
def stream_compilation(filename):
    filepath = os.path.join(COMPILATIONS_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    return send_file(filepath)


@app.route("/compilations", methods=["GET"])
def list_compilations():
    videos = []
    for ext in VIDEO_EXTENSIONS:
        for path in glob.glob(os.path.join(COMPILATIONS_DIR, f"*{ext}")):
            videos.append({"filename": os.path.basename(path), "size": os.path.getsize(path), "mtime": os.path.getmtime(path)})
    videos.sort(key=lambda v: v["mtime"], reverse=True)
    return jsonify(videos)


# ─── BROWSE ────────────────────────────────────────────────

@app.route("/browse", methods=["POST"])
def browse_profile():
    data = request.get_json()
    url = data.get("url", "").strip()
    offset = int(data.get("offset", 0))
    limit = int(data.get("limit", 10))
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    try:
        cmd = [
            "yt-dlp", "--flat-playlist", "--skip-download",
            "--print", "%(id)s\t%(title)s\t%(url)s\t%(duration)s",
            "--playlist-start", str(offset + 1),
            "--playlist-end", str(offset + limit),
            "--no-warnings",
        ]
        if os.path.exists(COOKIES_FILE):
            cmd += ["--cookies", COOKIES_FILE]
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0 and not result.stdout:
            return jsonify({"error": result.stderr[-400:]}), 500
        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                videos.append({
                    "id": parts[0],
                    "title": parts[1] if parts[1] != "NA" else parts[0],
                    "url": parts[2],
                    "duration": parts[3] if len(parts) > 3 and parts[3] != "NA" else None
                })
        return jsonify({"videos": videos, "offset": offset, "count": len(videos)})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out — try again"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
