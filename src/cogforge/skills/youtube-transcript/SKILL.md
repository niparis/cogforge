---
name: youtube-transcript
description: Use when the user provides a YouTube URL and asks to fetch, download, save, summarize, or process the video's transcript/subtitles using youtube-transcript-api. Do not use for video/audio downloads.
---

# YouTube Transcript

## Purpose

Fetch and save a YouTube transcript as a Markdown file with metadata frontmatter.

## Workflow

1. Run:
   ```
   cogforge sync youtube --url <URL> --format json
   ```

2. If exit code 0: the transcript is saved to `inbox/youtube/<video-slug>/index.md` with YAML frontmatter.

3. If exit code != 0: check the JSON output for the error reason. Possible failures:
   - Video unavailable or private
   - No transcript available for this video
   - yt-dlp not installed

4. The CLI handles: metadata fetching, transcript fetching, Markdown formatting, frontmatter assembly, and state file creation.

## Output

Success:
```
cogforge sync youtube --url <URL>
# Returns JSON with source_ids, new_count=1, error_count=0
```

Failure:
```
# Returns JSON with error description and non-zero exit code
```

## Rules

- Do not download video or audio.
- Do not claim to have watched the video.
- Do not claim success unless the sync command returns exit code 0.
