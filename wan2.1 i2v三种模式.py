import tkinter as tk
from tkinter import messagebox, ttk, scrolledtext, filedialog
import requests
import json
import os
from PIL import Image, ImageTk
import webbrowser
from datetime import datetime
import time
import threading
import urllib.request
import tempfile
import configparser
import sqlite3
from functools import partial


class AliyunVideoGenerationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("阿里云智能视频生成工具")
        self.root.geometry("950x750")

        self.current_task_id = None
        self.polling_active = False
        self.temp_dir = tempfile.mkdtemp()  # 创建临时目录存储测试图片

        # 定义可用的模型和对应的模式
        self.models = {
            "wanx2.1-kf2v-plus": "首尾帧生成模式",
            "wanx2.1-t2v-turbo": "文本生成模式",
            "wanx2.1-i2v-turbo": "单图生成模式"
        }

        # 当前选择的模型
        self.current_model = tk.StringVar(value="wanx2.1-kf2v-plus")

        # 配置文件路径
        self.config_file = os.path.join(os.path.expanduser("~"), ".aliyun_video_generator_config.ini")

        # 数据库路径
        self.db_file = os.path.join(os.path.expanduser("~"), ".aliyun_video_generator_history.db")

        # 创建/连接数据库
        self.setup_database()

        # 创建主框架前先加载配置
        self.load_config()

        self.create_menu()

        # 创建主滚动框架
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # 创建滚动Canvas
        self.canvas = tk.Canvas(self.main_frame)
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )

        self.canvas_frame = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # 设置滚动事件绑定
        self.canvas.bind('<Configure>', self.on_canvas_resize)
        self.scrollable_frame.bind('<Enter>', self.bind_mousewheel)
        self.scrollable_frame.bind('<Leave>', self.unbind_mousewheel)

        # 布局滚动组件
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.create_widgets()

    def setup_database(self):
        """设置历史记录数据库"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # 创建历史记录表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE,
            model TEXT,
            timestamp TEXT,
            prompt TEXT,
            status TEXT,
            video_url TEXT,
            request_json TEXT,
            response_json TEXT
        )
        ''')

        conn.commit()
        conn.close()

    def load_config(self):
        """加载配置文件，读取API key"""
        self.config = configparser.ConfigParser()

        if os.path.exists(self.config_file):
            self.config.read(self.config_file)
            self.saved_api_key = self.config.get('Settings', 'api_key', fallback='')
            self.save_api_key_var = tk.BooleanVar(
                value=self.config.getboolean('Settings', 'save_api_key', fallback=True))
        else:
            self.saved_api_key = ''
            self.save_api_key_var = tk.BooleanVar(value=True)

    def save_config(self):
        """保存配置到文件"""
        if not self.config.has_section('Settings'):
            self.config.add_section('Settings')

        if self.save_api_key_var.get():
            self.config.set('Settings', 'api_key', self.api_key_entry.get())
        else:
            self.config.set('Settings', 'api_key', '')

        self.config.set('Settings', 'save_api_key', str(self.save_api_key_var.get()))

        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)

    def on_canvas_resize(self, event):
        # 保证canvas_frame的宽度与canvas相同
        self.canvas.itemconfig(self.canvas_frame, width=event.width)

    def bind_mousewheel(self, event):
        # 绑定鼠标滚轮事件
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)

    def unbind_mousewheel(self, event):
        # 解绑鼠标滚轮事件
        self.canvas.unbind_all("<MouseWheel>")

    def on_mousewheel(self, event):
        # 处理鼠标滚轮事件
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def create_menu(self):
        menubar = tk.Menu(self.root)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="历史记录", command=self.show_history)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        menubar.add_cascade(label="文件", menu=file_menu)

        # Debug menu
        self.debug_menu = tk.Menu(menubar, tearoff=0)
        self.debug_menu.add_command(label="无调试信息", state=tk.DISABLED)
        menubar.add_cascade(label="调试", menu=self.debug_menu)

        # Video menu
        self.video_menu = tk.Menu(menubar, tearoff=0)
        self.video_menu.add_command(label="未生成视频", state=tk.DISABLED)
        menubar.add_cascade(label="视频", menu=self.video_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="图片URL指南", command=self.show_url_guide)
        help_menu.add_command(label="常见错误码", command=self.show_error_codes)
        help_menu.add_command(label="模型说明", command=self.show_model_info)
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.root.config(menu=menubar)

    def show_url_guide(self):
        guide_window = tk.Toplevel(self.root)
        guide_window.title("图片URL指南")
        guide_window.geometry("600x400")

        guide_text = """
图片URL格式指南：

1. API只接受直接可访问的图片URL，不支持需要登录或授权的URL

2. 支持的URL示例：
   - https://example.com/image.jpg
   - https://bucket-name.oss-cn-hangzhou.aliyuncs.com/image.png

3. 不支持的URL格式：
   - Google Drive共享链接 (https://drive.google.com/file/...)
   - 需要登录的云存储链接
   - 临时URL或有过期时间的URL

4. 如何获取直接图片URL：
   - 使用阿里云OSS、七牛云等对象存储服务上传图片
   - 使用图床服务如SM.MS、ImgBB等
   - 确保图片可以公开访问且URL直接指向图片文件

5. 图片要求：
   - 格式：JPEG、JPG、PNG(不支持透明通道)、BMP、WEBP
   - 大小：不超过10MB
   - 分辨率：360≤图像边长≤2000像素
        """

        text_widget = scrolledtext.ScrolledText(guide_window, wrap=tk.WORD)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.insert(tk.END, guide_text)
        text_widget.config(state=tk.DISABLED)

    def show_error_codes(self):
        error_window = tk.Toplevel(self.root)
        error_window.title("常见错误码")
        error_window.geometry("600x500")

        error_text = """
常见错误码及解决方案：

1. InvalidParameter.DataInspection
   说明：数据检查过程中下载媒体资源超时
   解决方案：
   - 确保图片URL可以直接访问
   - 不要使用Google Drive、Dropbox等需要授权的链接
   - 检查图片大小是否超过10MB

2. IPInfringementSuspect
   说明：输入数据（提示词或图像）涉嫌知识产权侵权
   解决方案：
   - 修改提示词，避免使用受版权保护的内容
   - 使用原创图片或版权允许的图片

3. DataInspectionFailed
   说明：输入数据（提示词或图像）可能包含敏感内容
   解决方案：
   - 修改提示词，避免敏感词汇
   - 更换不含敏感内容的图片

4. InternalError
   说明：服务异常
   解决方案：
   - 尝试重新提交请求
   - 联系服务提供商获取支持

注意：视频生成结果仅保留24小时，请及时下载保存。
        """

        text_widget = scrolledtext.ScrolledText(error_window, wrap=tk.WORD)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.insert(tk.END, error_text)
        text_widget.config(state=tk.DISABLED)

    def show_model_info(self):
        info_window = tk.Toplevel(self.root)
        info_window.title("模型说明")
        info_window.geometry("700x500")

        info_text = """
模型说明：

1. wanx2.1-kf2v-plus (首尾帧生成模式)
   说明：根据首尾两帧图像生成中间过渡的视频
   特性：
   - 需要提供两张图片URL（首帧和尾帧）
   - 可以通过提示词描述转场过程
   - 适合创建有明确起始和结束状态的视频

2. wanx2.1-t2v-turbo (文本生成模式)
   说明：纯文本提示词生成视频
   特性：
   - 仅需提供文本提示词
   - 生成速度更快
   - 适合简单场景的快速生成
   - 支持多种分辨率设置

3. wanx2.1-i2v-turbo (单图生成模式)
   说明：根据一张图片和文本提示词生成视频
   特性：
   - 需要提供一张图片URL和提示词
   - 基于输入图像生成连贯的视频动画
   - 适合为静态图片添加动态效果

注意事项：
- 提示词质量对生成结果影响很大，尽量具体描述
- 视频生成通常需要几分钟时间，请耐心等待
- 不同模型有不同的参数设置和适用场景
        """

        text_widget = scrolledtext.ScrolledText(info_window, wrap=tk.WORD)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.insert(tk.END, info_text)
        text_widget.config(state=tk.DISABLED)

    def show_history(self):
        """显示历史记录窗口"""
        history_window = tk.Toplevel(self.root)
        history_window.title("历史记录")
        history_window.geometry("900x600")

        # 创建工具栏
        toolbar = ttk.Frame(history_window)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(toolbar, text="刷新", command=lambda: self.load_history_data(history_tree)).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="删除选中", command=lambda: self.delete_history_item(history_tree)).pack(side=tk.LEFT,
                                                                                                      padx=5)
        ttk.Button(toolbar, text="导出记录", command=lambda: self.export_history()).pack(side=tk.LEFT, padx=5)

        # 创建TreeView显示历史记录
        columns = ("任务ID", "模型", "时间", "提示词", "状态", "操作")
        history_tree = ttk.Treeview(history_window, columns=columns, show="headings", height=15)

        # 设置列宽和标题
        history_tree.column("任务ID", width=150)
        history_tree.column("模型", width=120)
        history_tree.column("时间", width=120)
        history_tree.column("提示词", width=300)
        history_tree.column("状态", width=80)
        history_tree.column("操作", width=100)

        for col in columns:
            history_tree.heading(col, text=col)

        # 添加滚动条
        tree_scroll = ttk.Scrollbar(history_window, orient="vertical", command=history_tree.yview)
        history_tree.configure(yscrollcommand=tree_scroll.set)

        history_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 详情框架
        details_frame = ttk.LabelFrame(history_window, text="详细信息")
        details_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.details_text = scrolledtext.ScrolledText(details_frame, height=10, wrap=tk.WORD)
        self.details_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 绑定选择事件
        history_tree.bind("<<TreeviewSelect>>", lambda e: self.show_history_details(history_tree))

        # 加载历史数据
        self.load_history_data(history_tree)

    def load_history_data(self, tree):
        """从数据库加载历史记录到树视图"""
        # 清除现有项目
        for item in tree.get_children():
            tree.delete(item)

        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            cursor.execute("SELECT task_id, model, timestamp, prompt, status FROM history ORDER BY timestamp DESC")
            rows = cursor.fetchall()

            for row in rows:
                task_id, model, timestamp, prompt, status = row

                # 截断提示词
                short_prompt = prompt[:50] + "..." if len(prompt) > 50 else prompt

                # 插入数据
                tree.insert("", tk.END, values=(task_id, model, timestamp, short_prompt, status, "查看详情"))

            conn.close()

        except Exception as e:
            messagebox.showerror("错误", f"加载历史记录失败: {str(e)}")

    def show_history_details(self, tree):
        """显示选中历史记录的详细信息"""
        selected = tree.selection()
        if not selected:
            return

        # 获取选中的任务ID
        task_id = tree.item(selected[0], "values")[0]

        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT model, prompt, status, video_url, request_json, response_json FROM history WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()

            if row:
                model, prompt, status, video_url, request_json, response_json = row

                # 清空并更新详情文本
                self.details_text.delete(1.0, tk.END)

                details = f"任务ID: {task_id}\n"
                details += f"模型: {model}\n"
                details += f"状态: {status}\n\n"
                details += f"提示词: {prompt}\n\n"

                if video_url:
                    details += f"视频URL: {video_url}\n\n"

                    # 创建加载按钮
                    load_btn_frame = ttk.Frame(self.details_text)
                    self.details_text.window_create(tk.END, window=load_btn_frame)

                    ttk.Button(load_btn_frame, text="加载此任务",
                               command=lambda: self.load_task_from_history(task_id)).pack(side=tk.LEFT, padx=5)
                    ttk.Button(load_btn_frame, text="在浏览器中打开视频",
                               command=lambda: webbrowser.open(video_url)).pack(side=tk.LEFT, padx=5)

                    self.details_text.insert(tk.END, "\n\n")
                else:
                    # 只显示加载按钮
                    load_btn_frame = ttk.Frame(self.details_text)
                    self.details_text.window_create(tk.END, window=load_btn_frame)

                    ttk.Button(load_btn_frame, text="加载此任务",
                               command=lambda: self.load_task_from_history(task_id)).pack(side=tk.LEFT, padx=5)

                    self.details_text.insert(tk.END, "\n\n")

                details += "请求JSON:\n"
                details += request_json + "\n\n"
                details += "响应JSON:\n"
                details += response_json

                self.details_text.insert(tk.END, details)

            conn.close()

        except Exception as e:
            messagebox.showerror("错误", f"加载历史记录详情失败: {str(e)}")

    def load_task_from_history(self, task_id):
        """从历史记录加载任务到当前界面"""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT model, request_json, response_json, status, video_url FROM history WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()

            if row:
                model, request_json, response_json, status, video_url = row

                # 设置模型
                self.current_model.set(model)
                # 更新模型选择界面
                self.change_model_ui()

                # 填充请求和响应文本
                self.request_text.delete(1.0, tk.END)
                self.request_text.insert(tk.END, request_json)

                self.response_text.delete(1.0, tk.END)
                self.response_text.insert(tk.END, response_json)

                # 设置任务ID和状态
                self.current_task_id = task_id
                self.task_id_var.set(task_id)
                self.status_var.set(status)

                # 如果有视频URL，设置它
                if video_url:
                    self.video_url_var.set(video_url)
                    self.update_video_menu(video_url)

                # 填充输入字段
                request_data = json.loads(request_json)
                input_data = request_data.get("input", {})

                # 根据不同模型填充不同字段
                if model == "wanx2.1-kf2v-plus":
                    # 首尾帧模式
                    if "prompt" in input_data:
                        self.prompt_text.delete(1.0, tk.END)
                        self.prompt_text.insert(tk.END, input_data["prompt"])
                    if "first_frame_url" in input_data:
                        self.first_frame_entry.delete(0, tk.END)
                        self.first_frame_entry.insert(0, input_data["first_frame_url"])
                    if "last_frame_url" in input_data:
                        self.last_frame_entry.delete(0, tk.END)
                        self.last_frame_entry.insert(0, input_data["last_frame_url"])

                elif model == "wanx2.1-t2v-turbo":
                    # 纯文本模式
                    if "prompt" in input_data:
                        self.text_prompt.delete(1.0, tk.END)
                        self.text_prompt.insert(tk.END, input_data["prompt"])

                elif model == "wanx2.1-i2v-turbo":
                    # 单图模式
                    if "prompt" in input_data:
                        self.image_prompt.delete(1.0, tk.END)
                        self.image_prompt.insert(tk.END, input_data["prompt"])
                    if "img_url" in input_data:
                        self.image_url_entry.delete(0, tk.END)
                        self.image_url_entry.insert(0, input_data["img_url"])

                messagebox.showinfo("成功", f"已加载任务 {task_id}")

            conn.close()

        except Exception as e:
            messagebox.showerror("错误", f"加载任务失败: {str(e)}")

    def delete_history_item(self, tree):
        """删除选中的历史记录"""
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择要删除的记录")
            return

        if messagebox.askyesno("确认", "确定要删除选中的历史记录吗？"):
            for item in selected:
                task_id = tree.item(item, "values")[0]

                try:
                    conn = sqlite3.connect(self.db_file)
                    cursor = conn.cursor()

                    cursor.execute("DELETE FROM history WHERE task_id = ?", (task_id,))
                    conn.commit()
                    conn.close()

                    # 从树视图中删除
                    tree.delete(item)

                except Exception as e:
                    messagebox.showerror("错误", f"删除记录失败: {str(e)}")

    def export_history(self):
        """导出历史记录到JSON文件"""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON文件", "*.json"), ("所有文件", "*.*")],
            title="导出历史记录"
        )

        if not filepath:
            return

        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT task_id, model, timestamp, prompt, status, video_url, request_json, response_json FROM history"
            )
            rows = cursor.fetchall()

            history_data = []
            for row in rows:
                task_id, model, timestamp, prompt, status, video_url, request_json, response_json = row

                history_item = {
                    "task_id": task_id,
                    "model": model,
                    "timestamp": timestamp,
                    "prompt": prompt,
                    "status": status,
                    "video_url": video_url,
                    "request_json": json.loads(request_json) if request_json else None,
                    "response_json": json.loads(response_json) if response_json else None
                }

                history_data.append(history_item)

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)

            messagebox.showinfo("成功", f"历史记录已导出到 {filepath}")

            conn.close()

        except Exception as e:
            messagebox.showerror("错误", f"导出历史记录失败: {str(e)}")

    def save_to_history(self, task_id, model, prompt, status, video_url="", request_json="", response_json=""):
        """保存任务到历史记录数据库"""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 检查任务是否已存在
            cursor.execute("SELECT id FROM history WHERE task_id = ?", (task_id,))
            existing = cursor.fetchone()

            if existing:
                # 更新现有记录
                cursor.execute(
                    """UPDATE history SET 
                    model = ?, timestamp = ?, prompt = ?, status = ?, 
                    video_url = ?, request_json = ?, response_json = ? 
                    WHERE task_id = ?""",
                    (model, timestamp, prompt, status, video_url, request_json, response_json, task_id)
                )
            else:
                # 插入新记录
                cursor.execute(
                    """INSERT INTO history 
                    (task_id, model, timestamp, prompt, status, video_url, request_json, response_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (task_id, model, timestamp, prompt, status, video_url, request_json, response_json)
                )

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"保存历史记录失败: {str(e)}")
            # 这里我们不显示错误消息框，以免干扰用户操作

    def create_widgets(self):
        # 顶部框架用于通用设置
        top_frame = ttk.Frame(self.scrollable_frame)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        # API凭证
        cred_frame = ttk.LabelFrame(top_frame, text="API凭证")
        cred_frame.pack(fill=tk.X, padx=5, pady=5)

        cred_grid = ttk.Frame(cred_frame, padding="5")
        cred_grid.pack(fill=tk.X, expand=True)

        ttk.Label(cred_grid, text="DashScope API Key:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.api_key_entry = ttk.Entry(cred_grid, width=40, show="*")
        self.api_key_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W + tk.E)

        # 如果有保存的API key，自动填充
        if self.saved_api_key:
            self.api_key_entry.insert(0, self.saved_api_key)

        # 添加保存API key的选项
        self.save_api_key_check = ttk.Checkbutton(cred_grid, text="记住API Key", variable=self.save_api_key_var,
                                                  command=self.save_config)
        self.save_api_key_check.grid(row=0, column=2, padx=5, pady=5)

        cred_grid.columnconfigure(1, weight=1)

        # 模型选择框架
        model_frame = ttk.LabelFrame(top_frame, text="模型选择")
        model_frame.pack(fill=tk.X, padx=5, pady=5)

        model_grid = ttk.Frame(model_frame, padding="5")
        model_grid.pack(fill=tk.X, expand=True)

        ttk.Label(model_grid, text="选择模型:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        model_combobox = ttk.Combobox(model_grid, textvariable=self.current_model,
                                      values=list(self.models.keys()), state="readonly", width=20)
        model_combobox.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        model_combobox.bind("<<ComboboxSelected>>", lambda e: self.change_model_ui())

        # 显示当前模型的模式说明
        self.model_mode_var = tk.StringVar()
        self.update_model_mode_label()  # 初始化显示
        ttk.Label(model_grid, textvariable=self.model_mode_var, font=("", 9, "italic")).grid(
            row=0, column=2, sticky=tk.W, padx=5, pady=5)

        # 创建notebook with tabs
        self.notebook = ttk.Notebook(self.scrollable_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 创建tabs
        self.input_frame = ttk.Frame(self.notebook)
        self.result_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.input_frame, text="输入参数")
        self.notebook.add(self.result_frame, text="API结果")

        # 创建各种模型的输入界面框架
        self.kf2v_frame = ttk.Frame(self.input_frame)  # 首尾帧模式
        self.t2v_frame = ttk.Frame(self.input_frame)  # 文本生成模式
        self.i2v_frame = ttk.Frame(self.input_frame)  # 单图生成模式

        # 创建各种模型的输入组件
        self.create_kf2v_widgets(self.kf2v_frame)  # 首尾帧模式
        self.create_t2v_widgets(self.t2v_frame)  # 文本生成模式
        self.create_i2v_widgets(self.i2v_frame)  # 单图生成模式

        # Result tab
        self.create_result_widgets(self.result_frame)

        # 初始化显示当前选择的模型界面
        self.change_model_ui()

        # 把生成按钮固定在底部
        bottom_frame = ttk.Frame(self.scrollable_frame)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)

        self.generate_btn = ttk.Button(bottom_frame, text="生成视频", command=self.generate_video)
        self.generate_btn.pack(side=tk.LEFT, padx=5)

        self.check_btn = ttk.Button(bottom_frame, text="检查任务状态", command=self.check_task_status, state=tk.DISABLED)
        self.check_btn.pack(side=tk.LEFT, padx=5)

        self.cancel_btn = ttk.Button(bottom_frame, text="取消轮询", command=self.cancel_polling, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=5)

        self.progress_var = tk.StringVar()
        self.progress_label = ttk.Label(bottom_frame, textvariable=self.progress_var)
        self.progress_label.pack(side=tk.LEFT, padx=5)

    def update_model_mode_label(self):
        """更新模型模式说明标签"""
        model = self.current_model.get()
        mode = self.models.get(model, "未知模式")
        self.model_mode_var.set(f"当前选择: {mode}")

    def change_model_ui(self):
        """根据选择的模型切换显示对应的输入界面"""
        # 更新模型模式说明
        self.update_model_mode_label()

        # 隐藏所有模型界面
        for frame in [self.kf2v_frame, self.t2v_frame, self.i2v_frame]:
            frame.pack_forget()

        # 显示选中的模型界面
        model = self.current_model.get()
        if model == "wanx2.1-kf2v-plus":
            self.kf2v_frame.pack(fill=tk.BOTH, expand=True)
        elif model == "wanx2.1-t2v-turbo":
            self.t2v_frame.pack(fill=tk.BOTH, expand=True)
        elif model == "wanx2.1-i2v-turbo":
            self.i2v_frame.pack(fill=tk.BOTH, expand=True)

    def create_kf2v_widgets(self, parent):
        """创建首尾帧模式的输入组件"""
        # 创建内部滚动框架
        input_canvas = tk.Canvas(parent)
        input_scrollbar = ttk.Scrollbar(parent, orient="vertical", command=input_canvas.yview)
        input_scrollable_frame = ttk.Frame(input_canvas)

        input_scrollable_frame.bind(
            "<Configure>",
            lambda e: input_canvas.configure(
                scrollregion=input_canvas.bbox("all")
            )
        )

        input_canvas.create_window((0, 0), window=input_scrollable_frame, anchor="nw")
        input_canvas.configure(yscrollcommand=input_scrollbar.set)

        input_canvas.pack(side="left", fill="both", expand=True)
        input_scrollbar.pack(side="right", fill="y")

        # Images section
        image_frame = ttk.LabelFrame(input_scrollable_frame, text="帧图像")
        image_frame.pack(fill=tk.X, padx=5, pady=5)

        # Information label
        url_info = ttk.Label(image_frame,
                             text="注意: API只接受直接可访问的图片URL，不支持Google Drive等共享链接\n图片需要可公开访问且URL直接指向图片文件",
                             foreground="red")
        url_info.pack(fill=tk.X, padx=5, pady=5)

        # Frame for first and last images
        image_grid = ttk.Frame(image_frame, padding="10")
        image_grid.pack(fill=tk.X)

        # First Frame
        first_frame_container = ttk.LabelFrame(image_grid, text="首帧图像")
        first_frame_container.grid(row=0, column=0, padx=10, pady=10, sticky=tk.W + tk.E)

        ttk.Label(first_frame_container, text="图片URL:").pack(anchor=tk.W, padx=5, pady=2)
        self.first_frame_entry = ttk.Entry(first_frame_container)
        self.first_frame_entry.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(first_frame_container, text="测试URL有效性",
                   command=lambda: self.test_image_url(self.first_frame_entry.get(), self.first_frame_preview)).pack(
            pady=5, padx=5)

        # Frame for the image preview
        first_preview_frame = ttk.Frame(first_frame_container)
        first_preview_frame.pack(fill=tk.X, pady=5)

        self.first_frame_preview = ttk.Label(first_preview_frame)
        self.first_frame_preview.pack(padx=5, pady=5)

        # Last Frame
        last_frame_container = ttk.LabelFrame(image_grid, text="尾帧图像")
        last_frame_container.grid(row=0, column=1, padx=10, pady=10, sticky=tk.W + tk.E)

        ttk.Label(last_frame_container, text="图片URL:").pack(anchor=tk.W, padx=5, pady=2)
        self.last_frame_entry = ttk.Entry(last_frame_container)
        self.last_frame_entry.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(last_frame_container, text="测试URL有效性",
                   command=lambda: self.test_image_url(self.last_frame_entry.get(), self.last_frame_preview)).pack(
            pady=5, padx=5)

        # Frame for the image preview
        last_preview_frame = ttk.Frame(last_frame_container)
        last_preview_frame.pack(fill=tk.X, pady=5)

        self.last_frame_preview = ttk.Label(last_preview_frame)
        self.last_frame_preview.pack(padx=5, pady=5)

        # Configure grid weights
        image_grid.columnconfigure(0, weight=1)
        image_grid.columnconfigure(1, weight=1)

        # Text Prompt Frame
        prompt_frame = ttk.LabelFrame(input_scrollable_frame, text="提示词")
        prompt_frame.pack(fill=tk.X, padx=5, pady=5)

        prompt_info = ttk.Label(prompt_frame,
                                text="支持中英文，长度不超过800个字符。\n建议描写变化过程，例如运镜过程（镜头向左移动）或主体运动过程（人向前奔跑）",
                                wraplength=500)
        prompt_info.pack(padx=5, pady=5, anchor=tk.W)

        self.prompt_text = scrolledtext.ScrolledText(prompt_frame, height=4, wrap=tk.WORD)
        self.prompt_text.pack(fill=tk.X, padx=5, pady=5)
        self.prompt_text.insert(tk.END, "写实风格，镜头固定不动。")

        # Video Parameters
        param_frame = ttk.LabelFrame(input_scrollable_frame, text="视频参数")
        param_frame.pack(fill=tk.X, padx=5, pady=5)

        param_grid = ttk.Frame(param_frame, padding="5")
        param_grid.pack(fill=tk.X, expand=True)

        # Resolution
        ttk.Label(param_grid, text="分辨率:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.kf2v_resolution_var = tk.StringVar(value="720P")
        ttk.Combobox(param_grid, textvariable=self.kf2v_resolution_var,
                     values=["720P"], state="readonly", width=10).grid(row=0, column=1, padx=5, pady=5)

        # Prompt Extend
        ttk.Label(param_grid, text="智能改写:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        self.kf2v_prompt_extend_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(param_grid, variable=self.kf2v_prompt_extend_var).grid(row=0, column=3, padx=5, pady=5,
                                                                               sticky=tk.W)

        # Seed
        ttk.Label(param_grid, text="随机种子:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.kf2v_seed_var = tk.StringVar(value="")
        ttk.Entry(param_grid, textvariable=self.kf2v_seed_var, width=15).grid(row=1, column=1, padx=5, pady=5)

        seed_info = ttk.Label(param_grid, text="(可选, 0-2147483647)")
        seed_info.grid(row=1, column=2, columnspan=2, sticky=tk.W, padx=5, pady=5)

        # Configure param_grid
        param_grid.columnconfigure(1, weight=1)
        param_grid.columnconfigure(3, weight=1)

    def create_t2v_widgets(self, parent):
        """创建文本生成模式的输入组件"""
        # 创建内部滚动框架
        input_canvas = tk.Canvas(parent)
        input_scrollbar = ttk.Scrollbar(parent, orient="vertical", command=input_canvas.yview)
        input_scrollable_frame = ttk.Frame(input_canvas)

        input_scrollable_frame.bind(
            "<Configure>",
            lambda e: input_canvas.configure(
                scrollregion=input_canvas.bbox("all")
            )
        )

        input_canvas.create_window((0, 0), window=input_scrollable_frame, anchor="nw")
        input_canvas.configure(yscrollcommand=input_scrollbar.set)

        input_canvas.pack(side="left", fill="both", expand=True)
        input_scrollbar.pack(side="right", fill="y")

        # Text Prompt Frame
        prompt_frame = ttk.LabelFrame(input_scrollable_frame, text="文本提示词")
        prompt_frame.pack(fill=tk.X, padx=5, pady=5)

        prompt_info = ttk.Label(prompt_frame,
                                text="支持中英文，请输入要生成视频的场景描述。\n越详细的描述将获得更符合预期的结果。",
                                wraplength=500)
        prompt_info.pack(padx=5, pady=5, anchor=tk.W)

        self.text_prompt = scrolledtext.ScrolledText(prompt_frame, height=6, wrap=tk.WORD)
        self.text_prompt.pack(fill=tk.X, padx=5, pady=5)
        self.text_prompt.insert(tk.END, "一只小猫在月光下奔跑，写实风格。")

        # 示例提示按钮
        examples_frame = ttk.Frame(prompt_frame)
        examples_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(examples_frame, text="示例提示:").pack(side=tk.LEFT, padx=2)

        example_texts = [
            "一只金色小狗在草地上奔跑，阳光明媚",
            "水晶宫殿在云层中漂浮，魔幻风格",
            "宇航员在太空行走，地球在背景中旋转",
            "海浪拍打沙滩，夕阳西下，唯美风格"
        ]

        for text in example_texts:
            ttk.Button(examples_frame, text=text[:10] + "...",
                       command=partial(self.set_example_text, self.text_prompt, text)).pack(side=tk.LEFT, padx=2)

        # Video Parameters
        param_frame = ttk.LabelFrame(input_scrollable_frame, text="视频参数")
        param_frame.pack(fill=tk.X, padx=5, pady=5)

        param_grid = ttk.Frame(param_frame, padding="5")
        param_grid.pack(fill=tk.X, expand=True)

        # Size/Resolution
        ttk.Label(param_grid, text="分辨率:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.t2v_size_var = tk.StringVar(value="1280*720")
        ttk.Combobox(param_grid, textvariable=self.t2v_size_var,
                     values=["1280*720", "720*1280", "1024*1024"], state="readonly", width=15).grid(row=0, column=1,
                                                                                                    padx=5, pady=5)

        param_grid.columnconfigure(1, weight=1)

    def create_i2v_widgets(self, parent):
        """创建单图生成模式的输入组件"""
        # 创建内部滚动框架
        input_canvas = tk.Canvas(parent)
        input_scrollbar = ttk.Scrollbar(parent, orient="vertical", command=input_canvas.yview)
        input_scrollable_frame = ttk.Frame(input_canvas)

        input_scrollable_frame.bind(
            "<Configure>",
            lambda e: input_canvas.configure(
                scrollregion=input_canvas.bbox("all")
            )
        )

        input_canvas.create_window((0, 0), window=input_scrollable_frame, anchor="nw")
        input_canvas.configure(yscrollcommand=input_scrollbar.set)

        input_canvas.pack(side="left", fill="both", expand=True)
        input_scrollbar.pack(side="right", fill="y")

        # Image Frame
        image_frame = ttk.LabelFrame(input_scrollable_frame, text="输入图像")
        image_frame.pack(fill=tk.X, padx=5, pady=5)

        # Information label
        url_info = ttk.Label(image_frame,
                             text="注意: API只接受直接可访问的图片URL，不支持Google Drive等共享链接\n图片需要可公开访问且URL直接指向图片文件",
                             foreground="red")
        url_info.pack(fill=tk.X, padx=5, pady=5)

        image_url_frame = ttk.Frame(image_frame)
        image_url_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(image_url_frame, text="图片URL:").pack(side=tk.LEFT, padx=2)
        self.image_url_entry = ttk.Entry(image_url_frame, width=50)
        self.image_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.image_url_entry.insert(0, "https://cdn.translate.alibaba.com/r/wanx-demo-1.png")  # 默认示例图片

        ttk.Button(image_url_frame, text="测试URL有效性",
                   command=lambda: self.test_image_url(self.image_url_entry.get(), self.single_image_preview)).pack(
            side=tk.LEFT, pady=5, padx=5)

        # 图片预览
        preview_frame = ttk.Frame(image_frame)
        preview_frame.pack(fill=tk.X, pady=5, padx=5)

        self.single_image_preview = ttk.Label(preview_frame)
        self.single_image_preview.pack(padx=5, pady=5)

        # Text Prompt Frame
        prompt_frame = ttk.LabelFrame(input_scrollable_frame, text="提示词")
        prompt_frame.pack(fill=tk.X, padx=5, pady=5)

        prompt_info = ttk.Label(prompt_frame,
                                text="支持中英文，描述您希望图像如何动起来。\n例如：猫咪奔跑、花朵绽放、水面波动等。",
                                wraplength=500)
        prompt_info.pack(padx=5, pady=5, anchor=tk.W)

        self.image_prompt = scrolledtext.ScrolledText(prompt_frame, height=4, wrap=tk.WORD)
        self.image_prompt.pack(fill=tk.X, padx=5, pady=5)
        self.image_prompt.insert(tk.END, "一只猫在草地上奔跑")

        # 示例提示按钮
        examples_frame = ttk.Frame(prompt_frame)
        examples_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(examples_frame, text="示例提示:").pack(side=tk.LEFT, padx=2)

        example_texts = [
            "物体轻微摇晃，微风吹拂",
            "角色眨眼并微微转头",
            "花朵缓慢绽放",
            "水面波纹荡漾，落日余晖"
        ]

        for text in example_texts:
            ttk.Button(examples_frame, text=text[:10] + "...",
                       command=partial(self.set_example_text, self.image_prompt, text)).pack(side=tk.LEFT, padx=2)

        # Video Parameters
        param_frame = ttk.LabelFrame(input_scrollable_frame, text="视频参数")
        param_frame.pack(fill=tk.X, padx=5, pady=5)

        param_grid = ttk.Frame(param_frame, padding="5")
        param_grid.pack(fill=tk.X, expand=True)

        # Resolution
        ttk.Label(param_grid, text="分辨率:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.i2v_resolution_var = tk.StringVar(value="720P")
        ttk.Combobox(param_grid, textvariable=self.i2v_resolution_var,
                     values=["720P"], state="readonly", width=10).grid(row=0, column=1, padx=5, pady=5)

        # Prompt Extend
        ttk.Label(param_grid, text="智能改写:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        self.i2v_prompt_extend_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(param_grid, variable=self.i2v_prompt_extend_var).grid(row=0, column=3, padx=5, pady=5,
                                                                              sticky=tk.W)

        param_grid.columnconfigure(1, weight=1)
        param_grid.columnconfigure(3, weight=1)

    def set_example_text(self, text_widget, example_text):
        """设置示例文本到文本框"""
        text_widget.delete(1.0, tk.END)
        text_widget.insert(tk.END, example_text)

    def create_result_widgets(self, parent):
        # Task ID frame
        task_frame = ttk.Frame(parent)
        task_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(task_frame, text="任务ID:").pack(side=tk.LEFT, padx=2)
        self.task_id_var = tk.StringVar()
        task_id_entry = ttk.Entry(task_frame, textvariable=self.task_id_var, width=45)
        task_id_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Manual task check button
        ttk.Button(task_frame, text="手动查询任务",
                   command=self.check_manual_task).pack(side=tk.LEFT, padx=5)

        # Request frame
        req_frame = ttk.LabelFrame(parent, text="创建任务请求")
        req_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.request_text = scrolledtext.ScrolledText(req_frame, height=8, wrap=tk.WORD)
        self.request_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Task Status frame
        status_frame = ttk.LabelFrame(parent, text="任务状态")
        status_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(status_frame, text="当前状态:").pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="未开始")
        ttk.Label(status_frame, textvariable=self.status_var, font=("", 10, "bold")).pack(side=tk.LEFT, padx=2)

        # Response frame
        resp_frame = ttk.LabelFrame(parent, text="API响应")
        resp_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.response_text = scrolledtext.ScrolledText(resp_frame, height=12, wrap=tk.WORD)
        self.response_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Video URL frame
        video_frame = ttk.LabelFrame(parent, text="生成的视频")
        video_frame.pack(fill=tk.X, padx=5, pady=5)

        url_frame = ttk.Frame(video_frame)
        url_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(url_frame, text="视频URL:").pack(side=tk.LEFT, padx=2)

        self.video_url_var = tk.StringVar()
        url_entry = ttk.Entry(url_frame, textvariable=self.video_url_var, width=80)
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Buttons for video actions
        btn_frame = ttk.Frame(video_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(btn_frame, text="复制URL", command=self.copy_url).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="在浏览器中打开", command=self.open_video).pack(side=tk.LEFT, padx=5)
        ttk.Label(btn_frame, text="(注意：视频URL仅保存24小时，请及时下载！)", foreground="red").pack(side=tk.LEFT, padx=5)

    def test_image_url(self, url, preview_label):
        if not url:
            messagebox.showerror("错误", "请输入图片URL")
            return

        # 检查是否是Google Drive链接
        if "drive.google.com" in url:
            messagebox.showerror("不支持的URL",
                                 "Google Drive链接不能直接用于API。请获取直接可访问的图片URL。")
            return

        self.progress_var.set("正在测试URL有效性...")
        self.root.update()

        try:
            # 尝试下载图片
            temp_file = os.path.join(self.temp_dir, "temp_image.jpg")

            headers = {'User-Agent': 'Mozilla/5.0'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                content_type = response.info().get_content_type()
                if not content_type.startswith('image/'):
                    messagebox.showerror("错误", f"URL不是图片链接（内容类型: {content_type}）")
                    self.progress_var.set("URL测试失败: 不是图片链接")
                    return

                with open(temp_file, 'wb') as out_file:
                    out_file.write(response.read())

            # 显示预览
            self.update_image_preview(temp_file, preview_label)

            # 检查图片大小
            file_size = os.path.getsize(temp_file) / (1024 * 1024)  # 转换为MB
            if file_size > 10:
                messagebox.showwarning("警告", f"图片大小为{file_size:.2f}MB，超过10MB可能会导致API拒绝")

            # 检查图片分辨率
            img = Image.open(temp_file)
            width, height = img.size
            if width < 360 or height < 360:
                messagebox.showwarning("警告", f"图片分辨率({width}x{height})小于最小要求(360x360)")
            elif width > 2000 or height > 2000:
                messagebox.showwarning("警告", f"图片分辨率({width}x{height})超过最大限制(2000x2000)")

            self.progress_var.set("URL测试成功！")
            messagebox.showinfo("成功", "图片URL有效，可以正常访问。")

        except urllib.error.URLError as e:
            messagebox.showerror("错误", f"无法访问URL: {str(e)}")
            self.progress_var.set("URL测试失败: 无法访问")
        except Exception as e:
            messagebox.showerror("错误", f"测试URL时发生错误: {str(e)}")
            self.progress_var.set(f"URL测试失败: {str(e)}")

    def update_image_preview(self, filepath, preview_label):
        try:
            img = Image.open(filepath)
            aspect_ratio = img.width / img.height

            # Resize for preview while maintaining aspect ratio
            preview_width = 200
            preview_height = int(preview_width / aspect_ratio)

            if preview_height > 200:
                preview_height = 200
                preview_width = int(preview_height * aspect_ratio)

            img = img.resize((preview_width, preview_height), Image.LANCZOS)
            photo_img = ImageTk.PhotoImage(img)

            preview_label.config(image=photo_img)
            preview_label.image = photo_img  # Keep a reference
        except Exception as e:
            messagebox.showerror("错误", f"加载图像预览失败: {str(e)}")

    def update_debug_menu(self, success=True, message=""):
        self.debug_menu.delete(0, tk.END)
        timestamp = datetime.now().strftime("%H:%M:%S")

        if success:
            self.debug_menu.add_command(label=f"✓ {timestamp} - API调用成功", state=tk.DISABLED)
        else:
            self.debug_menu.add_command(label=f"✗ {timestamp} - 错误: {message}", state=tk.DISABLED)

    def update_video_menu(self, video_url=None):
        self.video_menu.delete(0, tk.END)
        if video_url:
            self.video_menu.add_command(label="在浏览器中打开视频", command=lambda: webbrowser.open(video_url))
            self.video_menu.add_command(label="复制视频URL", command=self.copy_url)
        else:
            self.video_menu.add_command(label="无可用视频", state=tk.DISABLED)

    def copy_url(self):
        url = self.video_url_var.get()
        if url:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            messagebox.showinfo("成功", "视频URL已复制到剪贴板。")
        else:
            messagebox.showinfo("提示", "无可用的视频URL供复制。")

    def check_manual_task(self):
        task_id = self.task_id_var.get().strip()
        if not task_id:
            messagebox.showerror("错误", "请输入任务ID")
            return

        api_key = self.api_key_entry.get()
        if not api_key:
            messagebox.showerror("错误", "请输入有效的API Key")
            return

        # 设置当前任务ID并检查状态
        self.current_task_id = task_id
        self.check_task_status()

    def validate_inputs(self):
        # API Key check
        api_key = self.api_key_entry.get()
        if not api_key:
            messagebox.showerror("错误", "请输入有效的DashScope API Key。")
            return False

        model = self.current_model.get()

        # 根据不同模型验证不同的输入
        if model == "wanx2.1-kf2v-plus":  # 首尾帧模式
            # URL check
            first_frame_url = self.first_frame_entry.get().strip()
            if not first_frame_url:
                messagebox.showerror("错误", "请输入首帧图像URL。")
                return False

            last_frame_url = self.last_frame_entry.get().strip()
            if not last_frame_url:
                messagebox.showerror("错误", "请输入尾帧图像URL。")
                return False

            # Check for Google Drive links
            if "drive.google.com" in first_frame_url or "drive.google.com" in last_frame_url:
                messagebox.showerror("错误", "Google Drive链接不能直接用于API。请使用直接可访问的图片URL。")
                return False

            # Prompt check
            prompt = self.prompt_text.get(1.0, tk.END).strip()
            if not prompt:
                messagebox.showerror("错误", "请输入提示词。")
                return False

            # Seed check (if provided)
            seed = self.kf2v_seed_var.get()
            if seed:
                try:
                    seed_val = int(seed)
                    if seed_val < 0 or seed_val > 2147483647:
                        messagebox.showerror("错误", "随机种子必须在0-2147483647范围内。")
                        return False
                except ValueError:
                    messagebox.showerror("错误", "随机种子必须是有效的整数。")
                    return False

        elif model == "wanx2.1-t2v-turbo":  # 文本生成模式
            # 验证提示词
            prompt = self.text_prompt.get(1.0, tk.END).strip()
            if not prompt:
                messagebox.showerror("错误", "请输入文本提示词。")
                return False

        elif model == "wanx2.1-i2v-turbo":  # 单图生成模式
            # 验证图片URL
            img_url = self.image_url_entry.get().strip()
            if not img_url:
                messagebox.showerror("错误", "请输入图片URL。")
                return False

            # Check for Google Drive links
            if "drive.google.com" in img_url:
                messagebox.showerror("错误", "Google Drive链接不能直接用于API。请使用直接可访问的图片URL。")
                return False

            # 验证提示词
            prompt = self.image_prompt.get(1.0, tk.END).strip()
            if not prompt:
                messagebox.showerror("错误", "请输入提示词。")
                return False

        return True

    def generate_video(self):
        if not self.validate_inputs():
            return

        # 在生成视频时保存配置
        self.save_config()

        # Disable UI during processing
        self.generate_btn.config(state=tk.DISABLED)
        self.progress_var.set("处理请求中...")
        self.root.update()

        # Clear previous results
        self.request_text.delete(1.0, tk.END)
        self.response_text.delete(1.0, tk.END)
        self.video_url_var.set("")
        self.task_id_var.set("")
        self.status_var.set("创建任务中...")

        api_key = self.api_key_entry.get()
        model = self.current_model.get()

        try:
            # 根据不同模型准备请求数据
            if model == "wanx2.1-kf2v-plus":  # 首尾帧模式
                # 准备接口URL
                api_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/image2video/video-synthesis"

                prompt = self.prompt_text.get(1.0, tk.END).strip()

                # Prepare input data
                input_data = {
                    "prompt": prompt,
                    "first_frame_url": self.first_frame_entry.get().strip(),
                    "last_frame_url": self.last_frame_entry.get().strip()
                }

                # Prepare parameters
                parameters = {
                    "resolution": self.kf2v_resolution_var.get(),
                    "prompt_extend": self.kf2v_prompt_extend_var.get()
                }

                # Add seed if provided
                if self.kf2v_seed_var.get():
                    parameters["seed"] = int(self.kf2v_seed_var.get())

            elif model == "wanx2.1-t2v-turbo":  # 文本生成模式
                # 准备接口URL
                api_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"

                prompt = self.text_prompt.get(1.0, tk.END).strip()

                # Prepare input data
                input_data = {
                    "prompt": prompt
                }

                # Prepare parameters
                parameters = {
                    "size": self.t2v_size_var.get()
                }

            elif model == "wanx2.1-i2v-turbo":  # 单图生成模式
                # 准备接口URL
                api_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"

                prompt = self.image_prompt.get(1.0, tk.END).strip()

                # Prepare input data
                input_data = {
                    "prompt": prompt,
                    "img_url": self.image_url_entry.get().strip()
                }

                # Prepare parameters
                parameters = {
                    "resolution": self.i2v_resolution_var.get(),
                    "prompt_extend": self.i2v_prompt_extend_var.get()
                }

            else:
                raise ValueError(f"不支持的模型: {model}")

            # Build complete request body
            request_body = {
                "model": model,
                "input": input_data,
                "parameters": parameters
            }

            # Show request parameters in UI
            request_json = json.dumps(request_body, indent=2, ensure_ascii=False)
            self.request_text.insert(tk.END, request_json)

            # Create request headers - 使用用户输入的API key
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "X-DashScope-Async": "enable"
            }

            self.progress_var.set("正在创建任务...")
            self.root.update()

            # Make the API request to create task
            response = requests.post(
                api_url,
                json=request_body,
                headers=headers
            )

            # Process the response
            if response.status_code in [200, 201, 202]:
                try:
                    response_json = response.json()
                    response_text = json.dumps(response_json, indent=2, ensure_ascii=False)
                    self.response_text.insert(tk.END, response_text)

                    # Extract task ID from response
                    if "output" in response_json and "task_id" in response_json["output"]:
                        task_id = response_json["output"]["task_id"]
                        self.current_task_id = task_id
                        self.task_id_var.set(task_id)

                        self.update_debug_menu(True)
                        self.progress_var.set("任务已创建，正在等待处理...")
                        self.status_var.set("等待中")

                        # 保存到历史记录
                        self.save_to_history(
                            task_id=task_id,
                            model=model,
                            prompt=prompt,
                            status="等待中",
                            request_json=request_json,
                            response_json=response_text
                        )

                        # Enable check button and start polling
                        self.check_btn.config(state=tk.NORMAL)

                        # Start polling thread
                        self.start_polling(task_id, api_key)

                    else:
                        self.update_debug_menu(False, "响应中没有任务ID")
                        self.progress_var.set("API调用成功但未返回任务ID。")
                        self.status_var.set("创建失败")
                        messagebox.showwarning("警告", "API调用成功但未返回任务ID。")

                except json.JSONDecodeError:
                    self.response_text.insert(tk.END, response.text)
                    self.update_debug_menu(False, "无法将响应解析为JSON")
                    self.progress_var.set("无法解析API响应。")
                    self.status_var.set("创建失败")
                    messagebox.showerror("错误", "无法将API响应解析为JSON。")
            else:
                error_text = response.text
                self.response_text.insert(tk.END, error_text)

                # 解析错误信息，提供更友好的提示
                try:
                    error_json = response.json()
                    error_code = error_json.get("code", "")
                    error_message = error_json.get("message", "")

                    if error_code == "InvalidParameter.DataInspection":
                        specific_error = "无法下载图片资源，请确保URL可直接访问。不要使用Google Drive等需要授权的链接。"
                    elif error_code == "IPInfringementSuspect":
                        specific_error = "输入数据（提示词或图像）涉嫌知识产权侵权，请修改内容。"
                    elif error_code == "DataInspectionFailed":
                        specific_error = "输入数据（提示词或图像）可能包含敏感内容，请修改内容。"
                    else:
                        specific_error = f"{error_code}: {error_message}"

                    self.update_debug_menu(False, specific_error)
                    self.progress_var.set(f"API请求失败: {specific_error}")
                    messagebox.showerror("错误", f"API请求失败: {specific_error}")
                except:
                    self.update_debug_menu(False, f"HTTP错误 {response.status_code}")
                    self.progress_var.set(f"API请求失败: HTTP {response.status_code}")
                    messagebox.showerror("错误", f"API请求失败，状态码: {response.status_code}")

                self.status_var.set("创建失败")

        except Exception as e:
            self.response_text.insert(tk.END, f"错误: {str(e)}")
            self.update_debug_menu(False, str(e))
            self.progress_var.set(f"错误: {str(e)}")
            self.status_var.set("创建失败")
            messagebox.showerror("错误", f"生成视频失败: {str(e)}")

        finally:
            # Re-enable UI
            self.generate_btn.config(state=tk.NORMAL)

    def start_polling(self, task_id, api_key):
        # Set up polling status
        self.polling_active = True
        self.cancel_btn.config(state=tk.NORMAL)

        # Start polling thread
        polling_thread = threading.Thread(
            target=self.poll_task_status,
            args=(task_id, api_key),
            daemon=True
        )
        polling_thread.start()

    def poll_task_status(self, task_id, api_key):
        polling_interval = 30  # seconds between checks
        max_attempts = 30  # about 15 minutes max
        attempts = 0

        while self.polling_active and attempts < max_attempts:
            # Wait for polling interval
            time.sleep(polling_interval)

            # Check if polling has been cancelled
            if not self.polling_active:
                break

            attempts += 1

            try:
                # Update UI from thread
                self.root.after(0, lambda: self.progress_var.set(f"检查任务状态... (尝试 {attempts}/{max_attempts})"))

                # Check task status
                url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }

                response = requests.get(url, headers=headers)

                if response.status_code == 200:
                    response_data = response.json()
                    response_text = json.dumps(response_data, indent=2, ensure_ascii=False)

                    # Update UI with response data
                    self.root.after(0, lambda: self.response_text.delete(1.0, tk.END))
                    self.root.after(0, lambda: self.response_text.insert(tk.END, response_text))

                    # Get task status
                    task_status = response_data.get("output", {}).get("task_status", "")

                    # Update status in UI
                    if task_status == "FAILED":
                        self.root.after(0, lambda: self.status_var.set("失败"))
                        self.root.after(0, lambda: self.progress_var.set("任务处理失败。"))

                        # 更新历史记录
                        self.root.after(0, lambda: self.save_to_history(
                            task_id=task_id,
                            model=self.current_model.get(),
                            prompt=self.get_current_prompt(),
                            status="失败",
                            response_json=response_text
                        ))

                        # 获取错误信息
                        error_code = response_data.get("code", "")
                        error_message = response_data.get("message", "")
                        if error_code and error_message:
                            error_info = f"{error_code}: {error_message}"
                        else:
                            error_info = "未知错误"

                        self.root.after(0, lambda msg=error_info: messagebox.showerror("错误", f"视频生成任务失败: {msg}"))
                        self.polling_active = False
                        break

                    elif task_status == "SUCCEEDED":
                        self.root.after(0, lambda: self.status_var.set("成功"))
                        self.root.after(0, lambda: self.progress_var.set("视频生成成功！"))

                        # Extract video URL
                        video_url = response_data.get("output", {}).get("video_url", "")

                        if video_url:
                            self.root.after(0, lambda: self.video_url_var.set(video_url))
                            self.root.after(0, lambda: self.update_video_menu(video_url))

                            # 更新历史记录
                            self.root.after(0, lambda: self.save_to_history(
                                task_id=task_id,
                                model=self.current_model.get(),
                                prompt=self.get_current_prompt(),
                                status="成功",
                                video_url=video_url,
                                response_json=response_text
                            ))

                            self.root.after(0, lambda: messagebox.showinfo("成功", "视频已成功生成！请在24小时内下载保存。"))
                        else:
                            self.root.after(0, lambda: messagebox.showwarning("警告", "任务成功但未返回视频URL。"))

                        self.polling_active = False
                        break

                    elif task_status == "RUNNING":
                        self.root.after(0, lambda: self.status_var.set("处理中"))
                        self.root.after(0, lambda: self.progress_var.set(f"视频正在生成中... (尝试 {attempts}/{max_attempts})"))

                        # 更新历史记录状态
                        self.root.after(0, lambda: self.save_to_history(
                            task_id=task_id,
                            model=self.current_model.get(),
                            prompt=self.get_current_prompt(),
                            status="处理中",
                            response_json=response_text
                        ))

                    else:  # PENDING or other
                        self.root.after(0, lambda: self.status_var.set(task_status))
                        self.root.after(0, lambda: self.progress_var.set(
                            f"任务状态: {task_status} (尝试 {attempts}/{max_attempts})"))

                        # 更新历史记录状态
                        self.root.after(0, lambda: self.save_to_history(
                            task_id=task_id,
                            model=self.current_model.get(),
                            prompt=self.get_current_prompt(),
                            status=task_status,
                            response_json=response_text
                        ))

                else:
                    error_msg = f"查询任务状态失败: HTTP {response.status_code}"
                    self.root.after(0, lambda: self.response_text.delete(1.0, tk.END))
                    self.root.after(0, lambda: self.response_text.insert(tk.END, response.text))
                    self.root.after(0, lambda: self.progress_var.set(error_msg))

            except Exception as e:
                error_msg = f"检查任务状态时发生错误: {str(e)}"
                self.root.after(0, lambda: self.progress_var.set(error_msg))

        # After polling ends
        self.root.after(0, lambda: self.cancel_btn.config(state=tk.DISABLED))

        if attempts >= max_attempts and self.polling_active:
            self.root.after(0, lambda: self.progress_var.set("达到最大尝试次数，请手动检查任务状态。"))
            self.root.after(0, lambda: messagebox.showinfo("提示", "达到最大尝试次数，请使用任务ID手动检查状态。"))
            self.polling_active = False

    def get_current_prompt(self):
        """获取当前模型的提示词"""
        model = self.current_model.get()
        if model == "wanx2.1-kf2v-plus":
            return self.prompt_text.get(1.0, tk.END).strip()
        elif model == "wanx2.1-t2v-turbo":
            return self.text_prompt.get(1.0, tk.END).strip()
        elif model == "wanx2.1-i2v-turbo":
            return self.image_prompt.get(1.0, tk.END).strip()
        return ""

    def check_task_status(self):
        if not self.current_task_id:
            messagebox.showinfo("提示", "没有活动的任务ID。")
            return

        api_key = self.api_key_entry.get()
        if not api_key:
            messagebox.showerror("错误", "请输入有效的API Key。")
            return

        self.progress_var.set("正在检查任务状态...")
        self.check_btn.config(state=tk.DISABLED)

        try:
            url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{self.current_task_id}"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                response_data = response.json()
                response_text = json.dumps(response_data, indent=2, ensure_ascii=False)
                self.response_text.delete(1.0, tk.END)
                self.response_text.insert(tk.END, response_text)

                # Get task status
                task_status = response_data.get("output", {}).get("task_status", "")
                self.status_var.set(task_status)

                # 更新历史记录
                self.save_to_history(
                    task_id=self.current_task_id,
                    model=self.current_model.get(),
                    prompt=self.get_current_prompt(),
                    status=task_status,
                    response_json=response_text
                )

                if task_status == "SUCCEEDED":
                    # Extract video URL
                    video_url = response_data.get("output", {}).get("video_url", "")

                    if video_url:
                        self.video_url_var.set(video_url)
                        self.update_video_menu(video_url)
                        self.progress_var.set("视频生成成功！")

                        # 更新历史记录
                        self.save_to_history(
                            task_id=self.current_task_id,
                            model=self.current_model.get(),
                            prompt=self.get_current_prompt(),
                            status="成功",
                            video_url=video_url,
                            response_json=response_text
                        )

                        messagebox.showinfo("成功", "视频已成功生成！请在24小时内下载保存。")
                    else:
                        self.progress_var.set("任务成功但未返回视频URL。")
                        messagebox.showwarning("警告", "任务成功但未返回视频URL。")

                elif task_status == "FAILED":
                    # 获取错误信息
                    error_code = response_data.get("code", "")
                    error_message = response_data.get("message", "")
                    if error_code and error_message:
                        error_info = f"{error_code}: {error_message}"
                    else:
                        error_info = "未知错误"

                    self.progress_var.set(f"任务处理失败: {error_info}")
                    messagebox.showerror("错误", f"视频生成任务失败: {error_info}")

                else:
                    self.progress_var.set(f"任务状态: {task_status}")
                    messagebox.showinfo("任务状态", f"当前任务状态: {task_status}\n\n处理需要7-10分钟，请耐心等待。")

            else:
                self.response_text.delete(1.0, tk.END)
                self.response_text.insert(tk.END, response.text)
                self.progress_var.set(f"查询任务状态失败: HTTP {response.status_code}")
                messagebox.showerror("错误", f"查询任务状态失败: HTTP {response.status_code}")

        except Exception as e:
            self.progress_var.set(f"检查任务状态时发生错误: {str(e)}")
            messagebox.showerror("错误", f"检查任务状态时发生错误: {str(e)}")

        finally:
            self.check_btn.config(state=tk.NORMAL)

    def cancel_polling(self):
        if self.polling_active:
            self.polling_active = False
            self.cancel_btn.config(state=tk.DISABLED)
            self.progress_var.set("自动任务检查已取消。")

    def open_video(self):
        video_url = self.video_url_var.get()
        if video_url:
            webbrowser.open(video_url)
        else:
            messagebox.showinfo("提示", "无可用的视频URL。")

    def __del__(self):
        # 清理临时目录
        try:
            for file in os.listdir(self.temp_dir):
                os.remove(os.path.join(self.temp_dir, file))
            os.rmdir(self.temp_dir)
        except:
            pass


def main():
    root = tk.Tk()
    app = AliyunVideoGenerationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
