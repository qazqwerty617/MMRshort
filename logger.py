"""
Логгер - система логирования для бота
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional
import yaml


class BotLogger:
    """Класс для настройки логирования"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Инициализация логгера
        
        Args:
            config_path: Путь к файлу конфигурации
        """
        # Загружаем конфигурацию
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        self.log_config = config['logging']
        self.logger = self._setup_logger()
    
    def _setup_logger(self) -> logging.Logger:
        """Настройка логгера"""
        # Создаём директорию для логов если её нет
        log_dir = os.path.dirname(self.log_config['file'])
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # Создаём логгер
        logger = logging.getLogger('PumpDetectorBot')
        logger.setLevel(self.log_config['level'])
        
        # Очищаем существующие обработчики
        logger.handlers.clear()
        
        # Формат логов
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Обработчик для файла (с ротацией)
        file_handler = RotatingFileHandler(
            self.log_config['file'],
            maxBytes=self.log_config['max_file_size_mb'] * 1024 * 1024,
            backupCount=self.log_config['backup_count'],
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # Обработчик для консоли
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        return logger
    
    def get_logger(self) -> logging.Logger:
        """Получить настроенный логгер"""
        return self.logger


# Глобальный экземпляр логгера
_global_logger: Optional[logging.Logger] = None


def setup_logging(config_path: str = "config.yaml") -> logging.Logger:
    """
    Инициализация глобального логгера
    
    Args:
        config_path: Путь к файлу конфигурации
        
    Returns:
        Настроенный логгер
    """
    global _global_logger
    if _global_logger is None:
        bot_logger = BotLogger(config_path)
        _global_logger = bot_logger.get_logger()
    return _global_logger


def get_logger() -> logging.Logger:
    """
    Получить глобальный логгер
    
    Returns:
        Логгер
    """
    global _global_logger
    if _global_logger is None:
        return setup_logging()
    return _global_logger
