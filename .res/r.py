import os
import sys
import time
import random
import psutil
from enum import Enum, IntEnum
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Callable
try:
    import GPUtil
except ImportError:
    GPUtil = None
from datetime import datetime
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent


class AnimationType(Enum):
    """动画类型枚举"""
    MAIN = "xiaoheichuchang2"
    BLINK = "zhayan" 
    ANGER = "shengqi"
    WALK_AWAY = "zoukai"
    SLEEP = "shuijiao"
    HEIXIU = "heixiu"
    HEIXIU_SLEEP = "heixiushuijiao"
    DRINK_MILK = "henai"
    CONFUSED = "yihuo"
    EAT_BURGER = "chihanbao"
    EAT_CHICKEN = "chijitui"
    SHAKE = "yao"
    ROLL = "gun1"
    GUITAR = "tanjita"
    PLAY_HEIXIU = "wanheixiu"
    BURP = "dage1"
    ANXIETY = "jiaolv"
    LEFT_WALK = "left_walk"
    RIGHT_WALK = "right_walk"
    SIT = "sit"


class AnimationPriority(IntEnum):
    """动画优先级（数值越大优先级越高）"""
    IDLE = 0          # 空闲状态
    BACKGROUND = 10   # 背景动画（眨眼等）
    INTERACTION = 20  # 交互动画
    SPECIAL = 30      # 特殊动画
    SYSTEM = 40       # 系统动画（强制睡眠、焦虑）
    FORCE = 50        # 强制动画（不可被打断）


@dataclass
class AnimationConfig:
    """动画配置"""
    folder: str
    frames: int
    timer_interval: int = 33
    loops: int = 1
    has_sound: bool = False
    sound_file: Optional[str] = None
    priority: AnimationPriority = AnimationPriority.INTERACTION
    interruptible: bool = True
    size_scale: float = 1.0  # 尺寸缩放比例
    on_complete: Optional[Callable] = None  # 完成后回调


class AnimationState:
    """动画状态管理类"""
    def __init__(self):
        self.current_animation = None
        self.current_priority = AnimationPriority.IDLE
        self.is_playing = False
        self.current_index = 0
        self.loop_count = 0
        self.start_time = 0
        self.direction = 1
        self.cached_frames = None
        self.original_size = None
    
    def can_interrupt(self, new_priority: AnimationPriority) -> bool:
        """检查是否可以被新动画打断"""
        if not self.is_playing:
            return True
        return new_priority > self.current_priority
    
    def reset(self):
        """重置状态"""
        self.current_animation = None
        self.current_priority = AnimationPriority.IDLE
        self.is_playing = False
        self.current_index = 0
        self.loop_count = 0
        self.cached_frames = None


def get_resource_path(relative_path: str) -> str:
    """获取资源文件路径，兼容PyInstaller打包"""
    try:
        # PyInstaller创建临时文件夹，将路径存储在_MEIPASS中
        base_path = sys._MEIPASS
    except Exception:
        # 开发环境下使用脚本所在目录
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    return os.path.join(base_path, relative_path)


class ResourceManager:
    """资源管理器 - 支持PyInstaller打包和资源复用"""
    _instance = None
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.frame_cache: Dict[str, List[QPixmap]] = {}
        self.image_cache: Dict[str, QPixmap] = {}
        self.sound_cache: Dict[str, QMediaContent] = {}
        self.base_pixmap_cache: Dict[str, QPixmap] = {}  # 原始尺寸缓存
        self._initialized = True
    
    def _get_cache_key(self, folder: str, filename: str = None, size: QSize = None) -> str:
        """生成缓存键"""
        key = folder
        if filename:
            key += f"/{filename}"
        if size:
            key += f"_{size.width()}x{size.height()}"
        return key
    
    def load_frames(self, folder_name: str, total_frames: int, size: QSize) -> List[QPixmap]:
        """加载动画帧并缓存"""
        cache_key = self._get_cache_key(folder_name, size=size)
        
        if cache_key in self.frame_cache:
            return self.frame_cache[cache_key]
        
        frames = []
        resource_dir = get_resource_path(folder_name)
        
        if not os.path.exists(resource_dir):
            print(f"警告: 资源目录不存在: {resource_dir}")
            return frames
        
        for i in range(1, total_frames + 1):
            img_path = os.path.join(resource_dir, f'{i}.png')
            
            if os.path.exists(img_path):
                pixmap = self._load_and_scale_pixmap(img_path, size)
                if pixmap and not pixmap.isNull():
                    frames.append(pixmap)
            else:
                print(f"警告: 图片文件不存在: {img_path}")
        
        self.frame_cache[cache_key] = frames
        return frames
    
    def load_single_image(self, folder_name: str, filename: str, size: QSize) -> Optional[QPixmap]:
        """加载单个图像并缓存"""
        cache_key = self._get_cache_key(folder_name, filename, size)
        
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]
        
        resource_dir = get_resource_path(folder_name)
        img_path = os.path.join(resource_dir, filename)
        
        if os.path.exists(img_path):
            pixmap = self._load_and_scale_pixmap(img_path, size)
            if pixmap and not pixmap.isNull():
                self.image_cache[cache_key] = pixmap
                return pixmap
        else:
            print(f"警告: 图片文件不存在: {img_path}")
        
        return None
    
    def _load_and_scale_pixmap(self, img_path: str, size: QSize) -> Optional[QPixmap]:
        """加载并缩放图片，复用原始图片"""
        try:
            # 检查原始图片缓存
            if img_path not in self.base_pixmap_cache:
                image = QImage(img_path)
                if image.isNull():
                    print(f"警告: 无法加载图片: {img_path}")
                    return None
                self.base_pixmap_cache[img_path] = QPixmap.fromImage(image)
            
            # 从缓存的原始图片缩放
            base_pixmap = self.base_pixmap_cache[img_path]
            if base_pixmap.size() == size:
                return base_pixmap
            
            return base_pixmap.scaled(
                size.width(), size.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        except Exception as e:
            print(f"错误: 加载图片时出错 {img_path}: {e}")
            return None
    
    def load_sound(self, folder_name: str, filename: str) -> Optional[QMediaContent]:
        """加载音频文件并缓存"""
        cache_key = self._get_cache_key(folder_name, filename)
        
        if cache_key in self.sound_cache:
            return self.sound_cache[cache_key]
        
        resource_dir = get_resource_path(folder_name)
        sound_path = os.path.join(resource_dir, filename)
        
        if os.path.exists(sound_path):
            try:
                sound = QMediaContent(QUrl.fromLocalFile(sound_path))
                self.sound_cache[cache_key] = sound
                return sound
            except Exception as e:
                print(f"警告: 无法加载音频文件 {sound_path}: {e}")
        else:
            print(f"警告: 音频文件不存在: {sound_path}")
        
        return None
    
    def preload_resources(self, animations: Dict[AnimationType, AnimationConfig], default_size: QSize):
        """预加载常用资源"""
        # 预加载主要动画的第一帧
        priority_animations = [
            AnimationType.MAIN, AnimationType.BLINK, AnimationType.SLEEP,
            AnimationType.ANGER, AnimationType.ANXIETY
        ]
        
        for anim_type in priority_animations:
            if anim_type in animations:
                config = animations[anim_type]
                size = QSize(
                    int(default_size.width() * config.size_scale),
                    int(default_size.height() * config.size_scale)
                )
                # 只预加载第一帧以节省内存
                frames = self.load_frames(config.folder, min(1, config.frames), size)
    
    def clear_cache(self):
        """清理缓存"""
        self.frame_cache.clear()
        self.image_cache.clear()
        self.sound_cache.clear()
        self.base_pixmap_cache.clear()


class SystemMonitor:
    """系统监控类"""
    def __init__(self):
        self.gpu_usage_cache = 0.0
        self.cpu_usage_cache = 0.0
        self.last_gpu_update = 0
        self.last_cpu_update = 0
        self.update_interval = 2.0
        
    def get_cpu_usage(self) -> float:
        """获取CPU占用率"""
        current_time = time.time()
        
        if current_time - self.last_cpu_update > self.update_interval:
            try:
                self.cpu_usage_cache = psutil.cpu_percent(interval=0.1)
            except Exception as e:
                print(f"获取CPU使用率失败: {e}")
                self.cpu_usage_cache = 0.0
            self.last_cpu_update = current_time
        
        return self.cpu_usage_cache
    
    def get_gpu_usage(self) -> float:
        """获取GPU占用率"""
        if not GPUtil:
            return 0.0
            
        current_time = time.time()
        
        if current_time - self.last_gpu_update > self.update_interval:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    self.gpu_usage_cache = gpus[0].load * 100
                else:
                    self.gpu_usage_cache = 0.0
            except Exception as e:
                print(f"获取GPU使用率失败: {e}")
                self.gpu_usage_cache = 0.0
            self.last_gpu_update = current_time
        
        return self.gpu_usage_cache


class DesktopPet(QWidget):
    tool_name = '桌面宠物'
    
    # 动画配置 - 统一管理所有动画参数
    ANIMATIONS = {
        AnimationType.MAIN: AnimationConfig(
            "xiaoheichuchang2", 34, 100, 1, False, None,
            AnimationPriority.IDLE, True
        ),
        AnimationType.BLINK: AnimationConfig(
            "zhayan", 2, 100, 1, False, None,
            AnimationPriority.BACKGROUND, True
        ),
        AnimationType.ANGER: AnimationConfig(
            "shengqi", 2, 100, 3, False, None,
            AnimationPriority.SPECIAL, False
        ),
        AnimationType.WALK_AWAY: AnimationConfig(
            "zoukai", 20, 100, 1, False, None,
            AnimationPriority.SPECIAL, False
        ),
        AnimationType.HEIXIU: AnimationConfig(
            "heixiu", 39, 33, 1, True, "heixiu.mp3",
            AnimationPriority.INTERACTION, True, 0.5
        ),
        AnimationType.DRINK_MILK: AnimationConfig(
            "henai", 163, 33, 3, False, None,
            AnimationPriority.INTERACTION, True
        ),
        AnimationType.CONFUSED: AnimationConfig(
            "yihuo", 39, 33, 1, True, "yihuo.mp3",
            AnimationPriority.INTERACTION, True
        ),
        AnimationType.EAT_BURGER: AnimationConfig(
            "chihanbao", 112, 33, 3, False, None,
            AnimationPriority.INTERACTION, True
        ),
        AnimationType.EAT_CHICKEN: AnimationConfig(
            "chijitui", 45, 33, 3, False, None,
            AnimationPriority.INTERACTION, True
        ),
        AnimationType.SHAKE: AnimationConfig(
            "yao", 28, 33, 1, False, None,
            AnimationPriority.INTERACTION, True
        ),
        AnimationType.ROLL: AnimationConfig(
            "gun1", 118, 33, 1, False, None,
            AnimationPriority.INTERACTION, True, 1.5
        ),
        AnimationType.GUITAR: AnimationConfig(
            "tanjita", 30, 33, 3, False, None,
            AnimationPriority.INTERACTION, True
        ),
        AnimationType.PLAY_HEIXIU: AnimationConfig(
            "wanheixiu", 33, 33, 3, False, None,
            AnimationPriority.INTERACTION, True
        ),
        AnimationType.BURP: AnimationConfig(
            "dage1", 45, 33, 1, False, None,
            AnimationPriority.INTERACTION, False
        ),
        AnimationType.ANXIETY: AnimationConfig(
            "jiaolv", 2, 100, -1, False, None,  # -1表示无限循环
            AnimationPriority.SYSTEM, False
        ),
        AnimationType.LEFT_WALK: AnimationConfig(
            "left_walk", 30, 33, -1, False, None,
            AnimationPriority.SPECIAL, True
        ),
        AnimationType.RIGHT_WALK: AnimationConfig(
            "right_walk", 30, 33, -1, False, None,
            AnimationPriority.SPECIAL, True
        ),
        AnimationType.SIT: AnimationConfig(
            "sit", 1, 100, -1, False, None,
            AnimationPriority.SPECIAL, True
        ),
    }
    
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        
        # 初始化核心组件
        self.resource_manager = ResourceManager()
        self.system_monitor = SystemMonitor()
        self.animation_state = AnimationState()
        
        # 核心属性
        self.original_size = QSize(200, 200)
        self.is_heixiu_mode = False
        self.is_force_sleeping = False
        self.last_interaction_time = time.time()
        self.click_timestamps = []
        
        # 自由活动相关
        self.free_active_type = None
        self.free_active_direction = 1
        self.free_active_start_time = 0
        self.free_active_duration = 0
        
        # 拖拽相关
        self.drag_position = None
        self.mouse_press_pos = None
        
        # 初始化组件
        try:
            self._setup_window()
            self._setup_ui()
            self.resource_manager.preload_resources(self.ANIMATIONS, self.original_size)
            self._load_basic_resources()
            self._setup_timers()
            self._setup_media_player()
        except Exception as e:
            print(f"初始化失败: {e}")
            return
        
        self.show()
    
    def _setup_window(self):
        """设置窗口属性"""
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(self.original_size)
    
    def _setup_ui(self):
        """设置UI组件"""
        # 主图像标签
        self.image_label = QLabel(self)
        self.image_label.setGeometry(0, 0, self.original_size.width(), self.original_size.height())
        self.image_label.setAlignment(Qt.AlignCenter)
        
        # 状态栏标签
        self.status_label = QLabel(self)
        self.status_label.setStyleSheet("color: white; background-color: rgba(0,0,0,128);")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setGeometry(
            0, self.original_size.height() - 20,
            self.original_size.width(), 20
        )
        
        # 睡眠提示标签
        self.sleep_hint_label = QLabel(self)
        self.sleep_hint_label.setText("主人该睡觉了，小黑好困")
        self.sleep_hint_label.setStyleSheet("color: red; font-weight: bold; background-color: rgba(0,0,0,128);")
        self.sleep_hint_label.setAlignment(Qt.AlignCenter)
        self.sleep_hint_label.setGeometry(0, 0, self.width(), 20)
        self.sleep_hint_label.hide()
    
    def _setup_media_player(self):
        """设置媒体播放器"""
        try:
            self.media_player = QMediaPlayer(self)
        except Exception as e:
            print(f"媒体播放器初始化失败: {e}")
            self.media_player = None
    
    def _load_basic_resources(self):
        """加载基础资源"""
        # 加载主动画帧
        self.main_frames = self._get_animation_frames(AnimationType.MAIN)
        
        # 加载睡觉图像
        self.sleep_image = self.resource_manager.load_single_image(
            "shuijiao", "1.png", self.original_size
        )
        self.heixiu_sleep_image = self.resource_manager.load_single_image(
            "heixiushuijiao", "1.png", self.original_size
        )
        
        # 显示第一帧或创建默认图像
        if self.main_frames:
            self.image_label.setPixmap(self.main_frames[0])
        else:
            # 如果没有加载到图片，创建一个默认的占位图像
            pixmap = QPixmap(self.original_size)
            pixmap.fill(Qt.blue)
            painter = QPainter(pixmap)
            painter.setPen(Qt.white)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "桌面宠物")
            painter.end()
            self.image_label.setPixmap(pixmap)
    
    def _get_animation_frames(self, animation_type: AnimationType) -> List[QPixmap]:
        """获取动画帧"""
        if animation_type not in self.ANIMATIONS:
            return []
        
        config = self.ANIMATIONS[animation_type]
        current_size = self.size()
        
        # 应用尺寸缩放
        scaled_size = QSize(
            int(current_size.width() * config.size_scale),
            int(current_size.height() * config.size_scale)
        )
        
        return self.resource_manager.load_frames(
            config.folder, config.frames, scaled_size
        )
    
    def _setup_timers(self):
        """设置定时器"""
        # 主定时器 - 处理空闲状态和背景动画
        self.main_timer = QTimer(self)
        self.main_timer.timeout.connect(self._on_main_timer)
        self.main_timer.start(100)
        
        # 动画更新定时器
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._update_current_animation)
        
        # 自由活动定时器
        self.free_active_timer = QTimer(self)
        self.free_active_timer.timeout.connect(self._update_free_active)
        
        # 状态更新定时器
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(3000)  # 3秒更新一次
        
        # 空闲检测定时器
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self._check_idle_time)
        self.idle_timer.start(60000)  # 1分钟检查一次
    
    def _start_animation(self, animation_type: AnimationType, force: bool = False) -> bool:
        """启动动画 - 改进的打断逻辑"""
        if animation_type not in self.ANIMATIONS:
            return False
        
        config = self.ANIMATIONS[animation_type]
        
        # 检查是否可以打断当前动画
        if not force and not self.animation_state.can_interrupt(config.priority):
            return False
        
        # 停止当前动画
        self._stop_current_animation()
        
        # 获取动画帧
        frames = self._get_animation_frames(animation_type)
        if not frames:
            print(f"警告: 无法加载动画帧 {animation_type}")
            return False
        
        # 设置动画状态
        self.animation_state.current_animation = animation_type
        self.animation_state.current_priority = config.priority
        self.animation_state.is_playing = True
        self.animation_state.current_index = 0
        self.animation_state.loop_count = 0
        self.animation_state.start_time = time.time()
        self.animation_state.cached_frames = frames
        
        # 调整窗口大小（如果需要）
        if config.size_scale != 1.0:
            self.animation_state.original_size = self.size()
            new_size = QSize(
                int(self.original_size.width() * config.size_scale),
                int(self.original_size.height() * config.size_scale)
            )
            self.resize(new_size)
            self.image_label.setGeometry(0, 0, new_size.width(), new_size.height())
        
        # 显示第一帧
        self.image_label.setPixmap(frames[0])
        
        # 播放音频
        if config.has_sound and config.sound_file and self.media_player:
            sound = self.resource_manager.load_sound(config.folder, config.sound_file)
            if sound:
                try:
                    self.media_player.setMedia(sound)
                    self.media_player.play()
                except Exception as e:
                    print(f"播放音频失败: {e}")
        
        # 启动动画定时器
        self.animation_timer.start(config.timer_interval)
        
        return True
    
    def _stop_current_animation(self):
        """停止当前动画"""
        self.animation_timer.stop()
        self.free_active_timer.stop()
        
        # 停止音频
        if self.media_player and self.media_player.state() == QMediaPlayer.PlayingState:
            try:
                self.media_player.stop()
            except Exception as e:
                print(f"停止音频失败: {e}")
        
        # 恢复窗口大小
        if self.animation_state.original_size:
            self.resize(self.animation_state.original_size)
            self.image_label.setGeometry(0, 0, 
                self.animation_state.original_size.width(), 
                self.animation_state.original_size.height())
            self.animation_state.original_size = None
    
    def _on_main_timer(self):
        """主定时器处理 - 空闲状态和背景动画"""
        # 如果有活跃动画，不处理背景动画
        if self.animation_state.is_playing or self._is_in_special_state():
            return
        
        # 随机眨眼
        if random.randint(1, 1000) <= 5:  # 0.5%概率眨眼
            self._start_animation(AnimationType.BLINK)
    
    def _update_current_animation(self):
        """更新当前动画"""
        if not self.animation_state.is_playing or not self.animation_state.cached_frames:
            return
        
        config = self.ANIMATIONS[self.animation_state.current_animation]
        frames = self.animation_state.cached_frames
        
        # 显示当前帧
        if self.animation_state.current_index < len(frames):
            self.image_label.setPixmap(frames[self.animation_state.current_index])
            self.animation_state.current_index += 1
        else:
            # 处理循环
            if config.loops == -1:  # 无限循环
                self.animation_state.current_index = 0
            else:
                self.animation_state.current_index = 0
                self.animation_state.loop_count += 1
                
                if self.animation_state.loop_count >= config.loops:
                    self._end_current_animation()
    
    def _end_current_animation(self):
        """结束当前动画"""
        current_type = self.animation_state.current_animation
        
        # 执行完成回调
        if current_type in self.ANIMATIONS:
            config = self.ANIMATIONS[current_type]
            if config.on_complete:
                try:
                    config.on_complete()
                except Exception as e:
                    print(f"动画完成回调执行失败: {e}")
        
        # 特殊处理某些动画的后续动作
        if current_type == AnimationType.ANGER:
            self._start_animation(AnimationType.WALK_AWAY, force=True)
            return
        elif current_type in [AnimationType.DRINK_MILK, AnimationType.EAT_BURGER, AnimationType.EAT_CHICKEN]:
            if random.randint(1, 100) <= 30:  # 30%概率打嗝
                self._start_animation(AnimationType.BURP, force=True)
                return
        
        # 停止动画
        self._stop_current_animation()
        self.animation_state.reset()
        
        # 显示静止帧
        if self.main_frames:
            self.image_label.setPixmap(self.main_frames[-1])
    
    def _is_in_special_state(self) -> bool:
        """检查是否在特殊状态"""
        return (self.is_force_sleeping or 
                self.free_active_type is not None or
                self.animation_state.current_animation in [
                    AnimationType.SLEEP, AnimationType.HEIXIU_SLEEP
                ])
    
    def _update_free_active(self):
        """更新自由活动"""
        if not self.free_active_type:
            return
        
        # 检查持续时间
        if (self.free_active_duration > 0 and 
            time.time() - self.free_active_start_time > self.free_active_duration):
            self._end_free_active()
            return
        
        # 更新动画
        if self.free_active_type in ['left_walk', 'right_walk']:
            self._update_walk_animation()
            self._move_window_horizontally(self.free_active_direction * 5)
        elif self.free_active_type == 'sit':
            frames = self._get_animation_frames(AnimationType.SIT)
            if frames:
                self.image_label.setPixmap(frames[0])
    
    def _update_walk_animation(self):
        """更新行走动画"""
        animation_type = (AnimationType.LEFT_WALK if self.free_active_type == 'left_walk' 
                         else AnimationType.RIGHT_WALK)
        frames = self._get_animation_frames(animation_type)
        
        if frames:
            frame_index = self.animation_state.current_index % len(frames)
            self.image_label.setPixmap(frames[frame_index])
            self.animation_state.current_index += 1
    
    def _move_window_horizontally(self, step: int):
        """水平移动窗口"""
        current_pos = self.pos()
        new_x = current_pos.x() + step
        
        try:
            screen_geometry = QApplication.desktop().availableGeometry()
        except Exception:
            # 如果获取屏幕几何信息失败，使用默认值
            screen_geometry = QRect(0, 0, 1920, 1080)
        
        # 边界检测和方向反转
        if new_x < screen_geometry.left():
            new_x = screen_geometry.left()
            self._reverse_walk_direction()
        elif new_x > screen_geometry.right() - self.width():
            new_x = screen_geometry.right() - self.width()
            self._reverse_walk_direction()
        
        self.move(new_x, current_pos.y())
    
    def _reverse_walk_direction(self):
        """反转行走方向"""
        self.free_active_direction *= -1
        
        if self.free_active_type == 'left_walk':
            self.free_active_type = 'right_walk'
        elif self.free_active_type == 'right_walk':
            self.free_active_type = 'left_walk'
        
        self.animation_state.current_index = 0
    
    def _end_free_active(self):
        """结束自由活动"""
        self.free_active_timer.stop()
        self.free_active_type = None
        self.animation_state.current_index = 0
        
        if self.main_frames:
            self.image_label.setPixmap(self.main_frames[-1])
    
    def _update_status(self):
        """更新状态信息"""
        try:
            current_time_str = datetime.now().strftime("%H:%M")
            cpu_usage = self.system_monitor.get_cpu_usage()
            gpu_usage = self.system_monitor.get_gpu_usage()
            
            self.status_label.setText(f"{current_time_str}|CPU:{cpu_usage:.1f}%|GPU:{gpu_usage:.1f}%")
            
            # 检查凌晨1点强制睡眠
            hour = datetime.now().hour
            if hour == 1 and not self.is_force_sleeping:
                self._enter_force_sleep()
            elif hour != 1 and self.is_force_sleeping:
                self._exit_force_sleep()
            
            # 检查高CPU/GPU使用率
            is_high_usage = cpu_usage > 90 or gpu_usage > 90
            is_currently_anxious = self.animation_state.current_animation == AnimationType.ANXIETY
            
            if is_high_usage and not is_currently_anxious and not self.is_force_sleeping:
                self._start_animation(AnimationType.ANXIETY, force=True)
            elif not is_high_usage and is_currently_anxious:
                self._end_current_animation()
        except Exception as e:
            print(f"更新状态失败: {e}")
    
    def _check_idle_time(self):
        """检查空闲时间"""
        try:
            idle_seconds = time.time() - self.last_interaction_time
            
            if idle_seconds > 600:  # 10分钟
                if self.is_heixiu_mode and not self._is_sleeping():
                    self._enter_heixiu_sleep()
                elif not self._is_sleeping() and not self.is_force_sleeping:
                    self._enter_sleep()
        except Exception as e:
            print(f"检查空闲时间失败: {e}")
    
    def _enter_sleep(self):
        """进入睡眠状态"""
        if self._is_sleeping() or self.is_force_sleeping:
            return
        
        self._stop_current_animation()
        self.animation_state.current_animation = AnimationType.SLEEP
        self.animation_state.current_priority = AnimationPriority.SYSTEM
        
        if self.sleep_image:
            self.image_label.setPixmap(self.sleep_image)
        else:
            # 如果没有睡眠图像，显示文字
            pixmap = QPixmap(self.size())
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setPen(Qt.white)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "💤")
            painter.end()
            self.image_label.setPixmap(pixmap)
    
    def _enter_heixiu_sleep(self):
        """进入嘿咻睡眠状态"""
        if not self.is_heixiu_mode:
            return
        
        self._stop_current_animation()
        self.animation_state.current_animation = AnimationType.HEIXIU_SLEEP
        self.animation_state.current_priority = AnimationPriority.SYSTEM
        
        if self.heixiu_sleep_image:
            self.image_label.setPixmap(self.heixiu_sleep_image)
        else:
            self._enter_sleep()  # 回退到普通睡眠
    
    def _enter_force_sleep(self):
        """进入强制睡眠状态"""
        self.is_force_sleeping = True
        self._enter_sleep()
        self.sleep_hint_label.show()
    
    def _exit_force_sleep(self):
        """退出强制睡眠状态"""
        self.is_force_sleeping = False
        self.animation_state.reset()
        self.sleep_hint_label.hide()
        
        if self.main_frames:
            self.image_label.setPixmap(self.main_frames[-1])
    
    def _is_sleeping(self) -> bool:
        """检查是否在睡眠状态"""
        return self.animation_state.current_animation in [
            AnimationType.SLEEP, AnimationType.HEIXIU_SLEEP
        ]
    
    def _wake_up(self):
        """唤醒"""
        if not self._is_sleeping() or self.is_force_sleeping:
            return
        
        self.animation_state.reset()
        if self.main_frames:
            self.image_label.setPixmap(self.main_frames[-1])
    
    def _check_anger_condition(self):
        """检查生气条件"""
        current_time = time.time()
        # 清理超过10秒的点击记录
        self.click_timestamps = [t for t in self.click_timestamps if current_time - t <= 10]
        self.click_timestamps.append(current_time)
        
        # 10秒内点击超过15次触发生气
        if len(self.click_timestamps) >= 15:
            self.click_timestamps.clear()
            self._start_animation(AnimationType.ANGER, force=True)
    
    def start_free_active(self):
        """开始自由活动"""
        if self.is_force_sleeping:
            return
        
        try:
            self._stop_current_animation()
            self.animation_state.reset()
            self.animation_state.current_index = 0
            self.free_active_start_time = time.time()
            
            # 随机选择活动类型
            rand_val = random.randint(1, 100)
            if rand_val <= 48:
                self.free_active_type = 'left_walk'
                self.free_active_direction = -1
                self.free_active_duration = 0
            elif rand_val <= 96:
                self.free_active_type = 'right_walk'
                self.free_active_direction = 1
                self.free_active_duration = 0
            else:
                self.free_active_type = 'sit'
                self.free_active_duration = 300  # 5分钟
            
            self.free_active_timer.start(33)
        except Exception as e:
            print(f"开始自由活动失败: {e}")
    
    def toggle_heixiu_mode(self):
        """切换嘿咻模式"""
        try:
            self.is_heixiu_mode = not self.is_heixiu_mode
            
            if self.is_heixiu_mode:
                # 启动嘿咻动画
                self._start_animation(AnimationType.HEIXIU, force=True)
            else:
                # 退出嘿咻模式
                self._stop_current_animation()
                self.animation_state.reset()
                
                # 恢复原始大小
                self.resize(self.original_size)
                self.image_label.setGeometry(0, 0, self.original_size.width(), self.original_size.height())
                
                if self.main_frames:
                    self.image_label.setPixmap(self.main_frames[-1])
        except Exception as e:
            print(f"切换嘿咻模式失败: {e}")
    
    # 事件处理
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if self.is_force_sleeping:
            return
        
        try:
            self.last_interaction_time = time.time()
            
            if event.button() == Qt.LeftButton:
                self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
                self.mouse_press_pos = event.pos()
                event.accept()
        except Exception as e:
            print(f"鼠标按下事件处理失败: {e}")
    
    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self.is_force_sleeping:
            return
        
        try:
            self.last_interaction_time = time.time()
            
            if event.buttons() == Qt.LeftButton and self.drag_position:
                self.move(event.globalPos() - self.drag_position)
                event.accept()
        except Exception as e:
            print(f"鼠标移动事件处理失败: {e}")
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if self.is_force_sleeping:
            return
        
        try:
            self.last_interaction_time = time.time()
            
            if event.button() == Qt.LeftButton:
                # 处理睡眠状态唤醒
                if self._is_sleeping():
                    self._wake_up()
                    event.accept()
                    return
                
                # 处理点击事件
                if (self.mouse_press_pos and 
                    (event.pos() - self.mouse_press_pos).manhattanLength() < 5):
                    
                    if self.is_heixiu_mode:
                        self._start_animation(AnimationType.HEIXIU)
                    else:
                        # 随机动作
                        rand_val = random.randint(1, 100)
                        if rand_val < 10:
                            self._start_animation(AnimationType.SHAKE)
                        elif rand_val < 20:
                            self._start_animation(AnimationType.CONFUSED)
                        else:
                            self._start_animation(AnimationType.BLINK)
                        
                        self._check_anger_condition()
                
                self.mouse_press_pos = None
                self.drag_position = None
                event.accept()
        except Exception as e:
            print(f"鼠标释放事件处理失败: {e}")
    
    def contextMenuEvent(self, event):
        """右键菜单事件"""
        if self.is_force_sleeping:
            return
        
        try:
            self.last_interaction_time = time.time()
            menu = self._create_context_menu()
            if menu:
                menu.exec_(event.globalPos())
        except Exception as e:
            print(f"右键菜单事件处理失败: {e}")
    
    def _create_context_menu(self) -> QMenu:
        """创建右键菜单"""
        try:
            menu = QMenu(self)
            
            if self.free_active_type:
                menu.addAction("退出自由活动", self._end_free_active)
                menu.addAction("退出", self.close)
                return menu
            
            # 动画速度子菜单
            speed_menu = menu.addMenu("动画速度")
            speed_menu.addAction("慢速 (200ms)", lambda: self._set_main_timer_speed(200))
            speed_menu.addAction("正常 (100ms)", lambda: self._set_main_timer_speed(100))
            speed_menu.addAction("快速 (50ms)", lambda: self._set_main_timer_speed(50))
            
            # 基本动作菜单
            menu.addAction("重新播放", self._restart_animation)
            menu.addAction("自由活动", self.start_free_active)
            
            heixiu_text = "关闭嘿咻模式" if self.is_heixiu_mode else "开启嘿咻模式"
            menu.addAction(heixiu_text, self.toggle_heixiu_mode)
            
            # 互动菜单
            if not self.is_heixiu_mode:
                interaction_menu = menu.addMenu("互动动作")
                interaction_menu.addAction("喝奶", lambda: self._start_animation(AnimationType.DRINK_MILK))
                interaction_menu.addAction("吃汉堡", lambda: self._start_animation(AnimationType.EAT_BURGER))
                interaction_menu.addAction("吃鸡腿", lambda: self._start_animation(AnimationType.EAT_CHICKEN))
                interaction_menu.addAction("摇摆", lambda: self._start_animation(AnimationType.SHAKE))
                interaction_menu.addAction("滚动", lambda: self._start_animation(AnimationType.ROLL))
                interaction_menu.addAction("弹吉他", lambda: self._start_animation(AnimationType.GUITAR))
                interaction_menu.addAction("玩嘿咻", lambda: self._start_animation(AnimationType.PLAY_HEIXIU))
            
            menu.addSeparator()
            menu.addAction("退出", self.close)
            
            return menu
        except Exception as e:
            print(f"创建右键菜单失败: {e}")
            return None
    
    def _set_main_timer_speed(self, speed: int):
        """设置主定时器速度"""
        try:
            self.main_timer.stop()
            self.main_timer.start(speed)
        except Exception as e:
            print(f"设置定时器速度失败: {e}")
    
    def _restart_animation(self):
        """重启动画"""
        try:
            self._stop_current_animation()
            self.animation_state.reset()
            self.is_heixiu_mode = False
            self.free_active_type = None
            self.last_interaction_time = time.time()
            
            # 恢复原始尺寸
            self.resize(self.original_size)
            self.image_label.setGeometry(0, 0, self.original_size.width(), self.original_size.height())
            
            if self.main_frames:
                self.image_label.setPixmap(self.main_frames[0])
            
            self.main_timer.start(100)
        except Exception as e:
            print(f"重启动画失败: {e}")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        try:
            # 停止所有定时器
            if hasattr(self, 'main_timer'):
                self.main_timer.stop()
            if hasattr(self, 'animation_timer'):
                self.animation_timer.stop()
            if hasattr(self, 'free_active_timer'):
                self.free_active_timer.stop()
            if hasattr(self, 'status_timer'):
                self.status_timer.stop()
            if hasattr(self, 'idle_timer'):
                self.idle_timer.stop()
            
            # 停止音频播放
            if self.media_player and self.media_player.state() == QMediaPlayer.PlayingState:
                self.media_player.stop()
            
            # 清理资源
            if hasattr(self, 'resource_manager'):
                self.resource_manager.clear_cache()
            
            event.accept()
        except Exception as e:
            print(f"关闭事件处理失败: {e}")
            event.accept()


def main():
    """主函数 - 添加异常处理和优雅启动"""
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(True)
        
        # 检查是否已有实例在运行（简单检查）
        import tempfile
        import fcntl
        import os
        
        lock_file_path = os.path.join(tempfile.gettempdir(), 'desktop_pet.lock')
        try:
            lock_file = open(lock_file_path, 'w')
            fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            print("桌面宠物已在运行中")
            return
        
        pet = DesktopPet()
        
        # 如果初始化失败，显示错误信息
        if not pet.main_frames:
            print("警告: 未能加载主要资源文件，请检查资源目录")
        
        sys.exit(app.exec_())
        
    except Exception as e:
        print(f"程序启动失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()