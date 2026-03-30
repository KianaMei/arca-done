#!/usr/bin/env python3
"""
Arca.live 表情包爬虫 GUI 启动器
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from pathlib import Path
import ctypes

# 适配高 DPI 屏幕 (2K/4K)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# 从环境变量读取账号密码
DEFAULT_USERNAME = os.environ.get("ARCA_USERNAME", "")
DEFAULT_PASSWORD = os.environ.get("ARCA_PASSWORD", "")


class ArcaScraperGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Arca.live 表情包爬虫 (Gui Ver)")
        
        # 增加默认窗口大小以适配高分屏
        self.root.geometry("1000x800")
        self.root.resizable(True, True)
        
        # 设置默认字体大小
        default_font = ("Microsoft YaHei UI", 10)
        self.root.option_add("*Font", default_font)
        
        self.running = False
        self.setup_ui()
        
    def setup_ui(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 网址输入
        url_frame = ttk.LabelFrame(main_frame, text="目标网址", padding="5")
        url_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.url_var = tk.StringVar(value="https://arca.live/e/")
        url_entry = ttk.Entry(url_frame, textvariable=self.url_var, font=("Consolas", 10))
        url_entry.pack(fill=tk.X, padx=5, pady=5)
        
        # 登录信息
        login_frame = ttk.LabelFrame(main_frame, text="登录信息（可选）", padding="5")
        login_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 用户名
        user_frame = ttk.Frame(login_frame)
        user_frame.pack(fill=tk.X, pady=2)
        ttk.Label(user_frame, text="用户名:", width=8).pack(side=tk.LEFT)
        self.username_var = tk.StringVar(value=DEFAULT_USERNAME)
        ttk.Entry(user_frame, textvariable=self.username_var, width=30).pack(side=tk.LEFT, padx=5)
        
        # 密码
        pass_frame = ttk.Frame(login_frame)
        pass_frame.pack(fill=tk.X, pady=2)
        ttk.Label(pass_frame, text="密码:", width=8).pack(side=tk.LEFT)
        self.password_var = tk.StringVar(value=DEFAULT_PASSWORD)
        self.pass_entry = ttk.Entry(pass_frame, textvariable=self.password_var, width=30)
        self.pass_entry.pack(side=tk.LEFT, padx=5)
        
        # 显示密码复选框
        self.show_pass_var = tk.BooleanVar(value=True)  # 默认显示密码
        ttk.Checkbutton(pass_frame, text="显示", variable=self.show_pass_var, 
                       command=self.toggle_password).pack(side=tk.LEFT, padx=5)
        self.toggle_password()  # 初始化显示状态
        
        # 输出目录
        output_frame = ttk.LabelFrame(main_frame, text="输出目录", padding="5")
        output_frame.pack(fill=tk.X, pady=(0, 10))
        
        dir_frame = ttk.Frame(output_frame)
        dir_frame.pack(fill=tk.X)
        self.output_dir_var = tk.StringVar(value="downloads")
        ttk.Entry(dir_frame, textvariable=self.output_dir_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(dir_frame, text="浏览...", command=self.browse_dir).pack(side=tk.RIGHT, padx=5)
        
        # 按钮区域
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.start_btn = ttk.Button(btn_frame, text="开始爬取", command=self.start_scraping)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self.stop_scraping, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="打开输出目录", command=self.open_output_dir).pack(side=tk.RIGHT, padx=5)
        
        # 日志输出
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, pady=(5, 0))
        
    def toggle_password(self):
        """切换密码显示/隐藏"""
        if self.show_pass_var.get():
            self.pass_entry.config(show="")  # 显示密码
        else:
            self.pass_entry.config(show="*")  # 隐藏密码
            
    def browse_dir(self):
        dir_path = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if dir_path:
            self.output_dir_var.set(dir_path)
            
    def open_output_dir(self):
        import os
        output_dir = Path(self.output_dir_var.get())
        if output_dir.exists():
            os.startfile(output_dir)
        else:
            messagebox.showinfo("提示", "输出目录不存在")
            
    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        
    def start_scraping(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("错误", "请输入目标网址")
            return
            
        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("正在爬取...")
        self.log_text.delete(1.0, tk.END)
        
        # 在新线程中运行爬虫
        thread = threading.Thread(target=self.run_scraper, daemon=True)
        thread.start()
        
    def stop_scraping(self):
        self.running = False
        self.status_var.set("正在停止...")
        
    def run_scraper(self):
        import subprocess
        
        url = self.url_var.get().strip()
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        output_dir = self.output_dir_var.get().strip()
        
        self.log(f"目标网址: {url}")
        self.log(f"用户名: {username}")
        self.log(f"输出目录: {output_dir}")
        self.log("-" * 50)
        
        try:
            # 构建命令
            script_path = Path(__file__).parent / "arca_scraper_dp.py"
            cmd = [sys.executable, str(script_path), url, output_dir]
            
            # 设置环境变量传递账号密码
            import os
            env = os.environ.copy()
            env["ARCA_USERNAME"] = username
            env["ARCA_PASSWORD"] = password
            
            # 运行爬虫
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                bufsize=1
            )
            
            # 读取输出
            while True:
                if not self.running:
                    process.terminate()
                    self.log("\n用户停止爬取")
                    break
                    
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    self.root.after(0, self.log, line.rstrip())
                    
            process.wait()
            
            if process.returncode == 0:
                self.root.after(0, self.on_complete, True)
            else:
                self.root.after(0, self.on_complete, False)
                
        except Exception as e:
            self.root.after(0, self.log, f"错误: {e}")
            self.root.after(0, self.on_complete, False)
            
    def on_complete(self, success):
        self.running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        
        if success:
            self.status_var.set("爬取完成！")
            self.log("\n✅ 爬取完成！")
        else:
            self.status_var.set("爬取失败或被中断")
            
    def run(self):
        self.root.mainloop()


def main():
    try:
        app = ArcaScraperGUI()
        app.run()
    except Exception as e:
        # 如果 GUI 崩溃，尝试弹出错误框
        try:
            messagebox.showerror("致命错误", f"程序启动失败:\n{e}")
        except:
            # 如果 tk 都没起来，打印到 stderr (bat 会暂停)
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()
