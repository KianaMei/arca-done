import os
import sys
from pathlib import Path
from moviepy import VideoFileClip, clips_array, ColorClip

def stitch_videos(source_dir, group_size=3):
    source_path = Path(source_dir)
    # 优先在 source_dir 找 mp4 (因为 video-only 模式可能直接下在 source_dir)
    # 或者 mp4/ 目录（如果是从旧逻辑移动过来的）
    # 这里我们只扫描 source_dir 下的 .mp4
    
    files = list(source_path.glob("*.mp4"))
    
    # 兼容 mp4/ 子目录
    if not files and (source_path / "mp4").exists():
        files = list((source_path / "mp4").glob("*.mp4"))
        
    # 去重并排序
    files = sorted(list(set(files)), key=lambda f: f.name)
    
    if not files:
        print(f"在 {source_path} 未找到 MP4 文件")
        return

    print(f"找到 {len(files)} 个视频文件，准备每 {group_size} 个一组进行横向拼接")
    
    output_dir = source_path / "stitched_gif"
    output_dir.mkdir(exist_ok=True)

    for i in range(0, len(files), group_size):
        group = files[i:i+group_size]
        if len(group) < group_size:
            print(f"最后 {len(group)} 个文件不足一组，跳过: {[f.name for f in group]}")
            break
            
        print(f"处理第 {i//group_size + 1} 组: {[f.name for f in group]}...", end=" ", flush=True)
        
        clips = []
        try:
            # 1. 扫描有效文件及尺寸
            valid_files = [f for f in group if f.stat().st_size > 0]
            if not valid_files:
                print("全组为空，跳过")
                continue
                
            ref_clip = VideoFileClip(str(valid_files[0]))
            ref_size = ref_clip.size
            ref_fps = ref_clip.fps or 30
            ref_duration = ref_clip.duration
            ref_clip.close()

            # 2. 加载 Clip
            for f in group:
                if f.stat().st_size == 0:
                    # 占位黑块
                    clips.append(ColorClip(size=ref_size, color=(0,0,0), duration=ref_duration or 1.0))
                else:
                    clips.append(VideoFileClip(str(f)))
            
            # 3. 横向拼接 [[c1, c2, c3]]
            final_clip = clips_array([clips])
            
            # 4. 输出 GIF
            out_name = f"stitched_{group[0].stem}.gif"
            out_path = output_dir / out_name
            
            final_clip.write_gif(
                str(out_path), 
                fps=min(ref_fps, 50), 
                logger=None
            )
            print(f"OK ({out_path.stat().st_size/1024:.1f} KB)")
            
        except Exception as e:
            print(f"失败 ({e})")
        finally:
            for c in clips:
                try: c.close()
                except: pass
            if 'final_clip' in locals():
                try: final_clip.close()
                except: pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python arca_stitcher.py <下载目录>")
    else:
        stitch_videos(sys.argv[1])
