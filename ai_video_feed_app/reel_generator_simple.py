# import librosa
# import subprocess
# import os
# import math
# import glob

# # -----------------------------
# # CONFIGURATION
# # -----------------------------
# FFMPEG_PATH = ""
# media_folder = ""
# music_file = os.path.join(media_folder, "music3.mp3")
# output_file = os.path.join(media_folder, "final_output_4.mp4")
# max_duration = 50  # seconds
# MAX_IMAGE_DURATION = 3  # seconds
# NORMALIZED_RESOLUTION = "1280:720"
# NORMALIZED_FPS = 30

# # -----------------------------
# # HELPER FUNCTION
# # -----------------------------
# def get_video_duration(path):
#     cmd = [
#         FFMPEG_PATH, "-i", path, "-show_entries", "format=duration",
#         "-v", "quiet", "-of", "csv=p=0"
#     ]
#     result = subprocess.run(cmd, capture_output=True, text=True)
#     try:
#         return float(result.stdout)
#     except:
#         return None

# def normalize_clip(input_path, output_path, is_image=False, duration=2):
#     """Normalize resolution, fps, codec for a clip (video or image)"""
#     cmd = [FFMPEG_PATH, "-y"]
#     if is_image:
#         cmd += ["-loop", "1", "-i", input_path, "-t", str(duration)]
#     else:
#         cmd += ["-i", input_path, "-t", str(duration)]
#     cmd += [
#         "-vf", f"scale={NORMALIZED_RESOLUTION},fps={NORMALIZED_FPS}",
#         "-c:v", "libx264", "-pix_fmt", "yuv420p",
#         "-c:a", "aac",
#         output_path
#     ]
#     subprocess.run(cmd, check=True)
#     return output_path

# # -----------------------------
# # STEP 0: COLLECT MEDIA FILES
# # -----------------------------
# media_files = sorted(glob.glob(os.path.join(media_folder, "*.*")))
# clips = []
# temp_files = []

# for f in media_files:
#     ext = f.lower().split(".")[-1]
#     if ext in ["mp4", "mov", "avi", "mkv"]:
#         clips.append({"path": f, "type": "video"})
#     elif ext in ["jpg", "jpeg", "png"]:
#         temp_clip = os.path.join(media_folder, f"tmp_{os.path.basename(f)}.mp4")
#         temp_files.append(temp_clip)
#         clips.append({"path": f, "type": "image", "tmp": temp_clip})

# # -----------------------------
# # STEP 1: ANALYZE MUSIC BEATS
# # -----------------------------
# y, sr = librosa.load(music_file, sr=None)
# tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
# beat_times = librosa.frames_to_time(beat_frames, sr=sr)
# beat_times = beat_times[beat_times <= max_duration]

# num_beats = len(beat_times)
# num_clips = len(clips)
# beats_per_clip = math.ceil(num_beats / num_clips)

# # -----------------------------
# # STEP 2: NORMALIZE & ASSIGN DURATIONS
# # -----------------------------
# trimmed_clips = []
# for i, clip in enumerate(clips):
#     start_beat = i * beats_per_clip
#     end_beat = min((i + 1) * beats_per_clip, num_beats)
#     if start_beat >= num_beats:
#         break
#     duration = beat_times[end_beat - 1] - beat_times[start_beat]

#     if clip["type"] == "video":
#         original_duration = get_video_duration(clip["path"]) or duration
#         duration = min(duration, original_duration)
#         output_path = os.path.join(media_folder, f"normalized_{os.path.basename(clip['path'])}")
#         normalize_clip(clip["path"], output_path, is_image=False, duration=duration)
#         trimmed_clips.append(output_path)
#     else:
#         duration = min(duration, MAX_IMAGE_DURATION)
#         output_path = clip["tmp"]
#         normalize_clip(clip["path"], output_path, is_image=True, duration=duration)
#         trimmed_clips.append(output_path)

# # -----------------------------
# # STEP 3: CREATE CONCAT FILE
# # -----------------------------
# concat_file = os.path.join(media_folder, "file_list.txt")
# with open(concat_file, "w") as f:
#     for clip in trimmed_clips:
#         f.write(f"file '{os.path.abspath(clip)}'\n")

# # -----------------------------
# # STEP 4: MERGE CLIPS AND ADD MUSIC
# # -----------------------------
# cmd_merge = [
#     FFMPEG_PATH, "-y",
#     "-f", "concat",
#     "-safe", "0",
#     "-i", concat_file,
#     "-i", music_file,
#     "-c:v", "libx264",
#     "-preset", "fast",
#     "-c:a", "aac",
#     "-shortest",
#     output_file
# ]
# subprocess.run(cmd_merge, check=True)

# # -----------------------------
# # STEP 5: CLEANUP TEMP FILES
# # -----------------------------
# for f in temp_files + trimmed_clips + [concat_file]:
#     try:
#         os.remove(f)
#     except:
#         pass

# print(f"✅ Final video saved as {output_file}")



