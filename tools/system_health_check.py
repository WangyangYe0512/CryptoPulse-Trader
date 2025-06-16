#!/usr/bin/env python3
"""
系统健康检查脚本
检查CryptoPulse Trader各个组件的健康状态和鲁棒性
"""

import sys
import os
import time
from datetime import datetime

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_manager import ConfigManager
from utils.notification_manager import NotificationManager
from utils.telegram_bot import TelegramBot
from utils.logger import setup_logging, trading_logger


class SystemHealthChecker:
    """系统健康检查器"""
    
    def __init__(self):
        """初始化健康检查器"""
        self.components = {}
        self.health_report = {
            'overall_health': 0,
            'components': {},
            'issues': [],
            'recommendations': [],
            'timestamp': datetime.now()
        }
        
        # 设置日志
        setup_logging()
        trading_logger.info("🏥 CryptoPulse Trader 系统健康检查")
        trading_logger.info("=" * 60)
    
    def run_health_check(self):
        """运行完整的健康检查"""
        try:
            # 1. 检查配置管理器
            self.check_config_manager()
            
            # 2. 检查Telegram机器人
            self.check_telegram_bot()
            
            # 3. 检查通知管理器
            self.check_notification_manager()
            
            # 4. 计算整体健康状态
            self.calculate_overall_health()
            
            # 5. 生成报告
            self.generate_health_report()
            
        except Exception as e:
            trading_logger.error(f"健康检查执行失败: {e}", exc_info=True)
            self.health_report['issues'].append(f"健康检查执行失败: {e}")
    
    def check_config_manager(self):
        """检查配置管理器"""
        trading_logger.info("🔧 检查配置管理器...")
        
        component_health = {
            'name': 'ConfigManager',
            'status': 'unknown',
            'health_score': 0,
            'issues': [],
            'details': {}
        }
        
        try:
            # 初始化配置管理器
            config_manager = ConfigManager()
            self.components['config_manager'] = config_manager
            
            # 检查基本功能
            config = config_manager.config
            if isinstance(config, dict):
                component_health['health_score'] += 40
                component_health['details']['config_loaded'] = True
            else:
                component_health['issues'].append("配置格式无效")
            
            # 检查关键配置项
            required_sections = ['notification', 'trading', 'exchanges', 'risk']
            missing_sections = []
            for section in required_sections:
                if section in config:
                    component_health['health_score'] += 15
                else:
                    missing_sections.append(section)
            
            if missing_sections:
                component_health['issues'].append(f"缺少配置项: {missing_sections}")
            
            # 设置状态
            if component_health['health_score'] >= 80:
                component_health['status'] = 'healthy'
            elif component_health['health_score'] >= 60:
                component_health['status'] = 'warning'
            else:
                component_health['status'] = 'error'
            
            trading_logger.info(f"✅ 配置管理器健康评分: {component_health['health_score']}/100")
            
        except Exception as e:
            component_health['status'] = 'error'
            component_health['issues'].append(f"初始化失败: {e}")
            trading_logger.error(f"❌ 配置管理器检查失败: {e}")
        
        self.health_report['components']['config_manager'] = component_health
    
    def check_telegram_bot(self):
        """检查Telegram机器人"""
        trading_logger.info("🤖 检查Telegram机器人...")
        
        component_health = {
            'name': 'TelegramBot',
            'status': 'unknown',
            'health_score': 0,
            'issues': [],
            'details': {}
        }
        
        try:
            config_manager = self.components.get('config_manager')
            if not config_manager:
                component_health['issues'].append("配置管理器不可用")
                component_health['status'] = 'error'
                self.health_report['components']['telegram_bot'] = component_health
                return
            
            # 初始化Telegram机器人
            telegram_bot = TelegramBot(config_manager)
            self.components['telegram_bot'] = telegram_bot
            
            # 检查基本状态
            if telegram_bot.enabled:
                component_health['health_score'] += 30
                component_health['details']['enabled'] = True
            else:
                component_health['details']['enabled'] = False
                component_health['issues'].append("Telegram功能已禁用")
            
            # 检查健康状态
            health_status = telegram_bot.get_health_status()
            if health_status.get('is_healthy'):
                component_health['health_score'] += 30
                component_health['details']['is_healthy'] = True
            else:
                component_health['issues'].append("Telegram机器人状态异常")
            
            # 检查熔断器状态
            circuit_status = health_status.get('circuit_breaker', {})
            if circuit_status.get('state') == 'CLOSED':
                component_health['health_score'] += 20
                component_health['details']['circuit_breaker'] = 'normal'
            else:
                component_health['issues'].append(f"熔断器状态: {circuit_status.get('state')}")
            
            # 检查错误统计
            error_stats = health_status.get('error_stats', {})
            total_errors = error_stats.get('total_errors', 0)
            if total_errors == 0:
                component_health['health_score'] += 20
                component_health['details']['error_count'] = 0
            elif total_errors < 10:
                component_health['health_score'] += 10
                component_health['details']['error_count'] = total_errors
                component_health['issues'].append(f"有 {total_errors} 个错误")
            else:
                component_health['issues'].append(f"错误过多: {total_errors}")
                component_health['details']['error_count'] = total_errors
            
            # 设置状态
            if component_health['health_score'] >= 80:
                component_health['status'] = 'healthy'
            elif component_health['health_score'] >= 60:
                component_health['status'] = 'warning'
            else:
                component_health['status'] = 'error'
            
            trading_logger.info(f"✅ Telegram机器人健康评分: {component_health['health_score']}/100")
            
        except Exception as e:
            component_health['status'] = 'error'
            component_health['issues'].append(f"检查失败: {e}")
            trading_logger.error(f"❌ Telegram机器人检查失败: {e}")
        
        self.health_report['components']['telegram_bot'] = component_health
    
    def check_notification_manager(self):
        """检查通知管理器"""
        trading_logger.info("📬 检查通知管理器...")
        
        component_health = {
            'name': 'NotificationManager',
            'status': 'unknown',
            'health_score': 0,
            'issues': [],
            'details': {}
        }
        
        try:
            config_manager = self.components.get('config_manager')
            if not config_manager:
                component_health['issues'].append("配置管理器不可用")
                component_health['status'] = 'error'
                self.health_report['components']['notification_manager'] = component_health
                return
            
            # 初始化通知管理器
            notification_manager = NotificationManager(config_manager)
            self.components['notification_manager'] = notification_manager
            
            # 等待初始化完成
            time.sleep(1)
            
            # 检查运行状态
            status = notification_manager.get_status()
            if status.get('is_running'):
                component_health['health_score'] += 25
                component_health['details']['is_running'] = True
            else:
                component_health['issues'].append("通知管理器未运行")
            
            # 检查队列状态
            queue_size = status.get('queue_size', 0)
            if queue_size < 10:
                component_health['health_score'] += 25
                component_health['details']['queue_size'] = queue_size
            elif queue_size < 50:
                component_health['health_score'] += 15
                component_health['details']['queue_size'] = queue_size
                component_health['issues'].append(f"队列积压: {queue_size}")
            else:
                component_health['issues'].append(f"队列积压严重: {queue_size}")
                component_health['details']['queue_size'] = queue_size
            
            # 检查故障保护状态
            failsafe = status.get('failsafe', {})
            if not failsafe.get('is_active'):
                component_health['health_score'] += 25
                component_health['details']['failsafe_active'] = False
            else:
                component_health['issues'].append("故障保护已激活")
            
            # 检查健康评分
            health_check = notification_manager.get_health_check()
            health_score = health_check.get('health_score', 0)
            if health_score >= 80:
                component_health['health_score'] += 25
            elif health_score >= 60:
                component_health['health_score'] += 15
            else:
                component_health['health_score'] += 5
            
            component_health['details']['internal_health_score'] = health_score
            
            # 合并问题列表
            internal_issues = health_check.get('issues', [])
            component_health['issues'].extend(internal_issues)
            
            # 设置状态
            if component_health['health_score'] >= 80:
                component_health['status'] = 'healthy'
            elif component_health['health_score'] >= 60:
                component_health['status'] = 'warning'
            else:
                component_health['status'] = 'error'
            
            trading_logger.info(f"✅ 通知管理器健康评分: {component_health['health_score']}/100")
            
            # 停止通知管理器
            notification_manager.stop()
            
        except Exception as e:
            component_health['status'] = 'error'
            component_health['issues'].append(f"检查失败: {e}")
            trading_logger.error(f"❌ 通知管理器检查失败: {e}")
        
        self.health_report['components']['notification_manager'] = component_health
    
    def calculate_overall_health(self):
        """计算整体健康状态"""
        components = self.health_report['components']
        
        if not components:
            self.health_report['overall_health'] = 0
            return
        
        # 计算加权平均分
        weights = {
            'config_manager': 0.3,  # 配置管理器最重要
            'telegram_bot': 0.2,    # Telegram机器人次要（因为是可选功能）
            'notification_manager': 0.5  # 通知管理器重要（包含多个子系统）
        }
        
        total_score = 0
        total_weight = 0
        
        for component_name, component_data in components.items():
            weight = weights.get(component_name, 0.1)
            score = component_data.get('health_score', 0)
            total_score += score * weight
            total_weight += weight
        
        self.health_report['overall_health'] = int(total_score / total_weight) if total_weight > 0 else 0
        
        # 收集所有问题
        all_issues = []
        for component_data in components.values():
            issues = component_data.get('issues', [])
            for issue in issues:
                all_issues.append(f"{component_data['name']}: {issue}")
        
        self.health_report['issues'] = all_issues
        
        # 生成建议
        overall_health = self.health_report['overall_health']
        if overall_health < 60:
            self.health_report['recommendations'].append("系统存在严重问题，建议立即处理")
        elif overall_health < 80:
            self.health_report['recommendations'].append("系统存在一些问题，建议尽快处理")
        
        if all_issues:
            self.health_report['recommendations'].append("检查并修复所有报告的问题")
        
        if 'telegram' in str(all_issues).lower():
            self.health_report['recommendations'].append("检查Telegram配置和网络连接")
        
        self.health_report['recommendations'].append("定期运行健康检查")
    
    def generate_health_report(self):
        """生成健康报告"""
        trading_logger.info("")
        trading_logger.info("=" * 60)
        trading_logger.info("📊 系统健康报告")
        trading_logger.info("=" * 60)
        
        overall_health = self.health_report['overall_health']
        
        # 整体健康状态
        if overall_health >= 90:
            status_emoji = "🟢"
            status_text = "优秀"
        elif overall_health >= 80:
            status_emoji = "🟡"
            status_text = "良好"
        elif overall_health >= 60:
            status_emoji = "🟠"
            status_text = "一般"
        else:
            status_emoji = "🔴"
            status_text = "需要关注"
        
        trading_logger.info(f"{status_emoji} 整体健康状态: {status_text} ({overall_health}/100)")
        trading_logger.info("")
        
        # 组件状态
        trading_logger.info("📋 组件状态详情:")
        for component_name, component_data in self.health_report['components'].items():
            status = component_data['status']
            score = component_data['health_score']
            
            status_emoji = {
                'healthy': '🟢',
                'warning': '🟡',
                'error': '🔴',
                'unknown': '⚪'
            }.get(status, '⚪')
            
            trading_logger.info(f"  {status_emoji} {component_data['name']}: {score}/100 ({status})")
            
            # 显示问题
            issues = component_data.get('issues', [])
            if issues:
                for issue in issues[:3]:  # 只显示前3个问题
                    trading_logger.info(f"    ⚠️  {issue}")
                if len(issues) > 3:
                    trading_logger.info(f"    ... 和其他 {len(issues) - 3} 个问题")
        
        trading_logger.info("")
        
        # 问题汇总
        if self.health_report['issues']:
            trading_logger.info("⚠️ 发现的问题:")
            for i, issue in enumerate(self.health_report['issues'][:5], 1):
                trading_logger.info(f"  {i}. {issue}")
            if len(self.health_report['issues']) > 5:
                trading_logger.info(f"  ... 和其他 {len(self.health_report['issues']) - 5} 个问题")
            trading_logger.info("")
        
        # 建议
        if self.health_report['recommendations']:
            trading_logger.info("🔧 建议:")
            for i, rec in enumerate(self.health_report['recommendations'], 1):
                trading_logger.info(f"  {i}. {rec}")
            trading_logger.info("")
        
        # 鲁棒性评估
        trading_logger.info("🛡️ 鲁棒性评估:")
        
        # 错误处理能力
        telegram_health = self.health_report['components'].get('telegram_bot', {}).get('health_score', 0)
        if telegram_health > 0 or not self.health_report['components'].get('telegram_bot', {}).get('details', {}).get('enabled'):
            trading_logger.info("  ✅ Telegram故障隔离: 正常")
        else:
            trading_logger.info("  ❌ Telegram故障隔离: 异常")
        
        # 自愈能力
        failsafe_active = any(
            comp.get('details', {}).get('failsafe_active', False)
            for comp in self.health_report['components'].values()
        )
        if not failsafe_active:
            trading_logger.info("  ✅ 故障保护机制: 正常")
        else:
            trading_logger.info("  ⚠️  故障保护机制: 已激活")
        
        # 配置完整性
        config_health = self.health_report['components'].get('config_manager', {}).get('health_score', 0)
        if config_health >= 80:
            trading_logger.info("  ✅ 配置完整性: 良好")
        else:
            trading_logger.info("  ⚠️  配置完整性: 需要检查")
        
        trading_logger.info("")
        trading_logger.info("=" * 60)
        trading_logger.info(f"报告生成时间: {self.health_report['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
        trading_logger.info("=" * 60)


def main():
    """主函数"""
    checker = SystemHealthChecker()
    
    try:
        checker.run_health_check()
        
    except KeyboardInterrupt:
        trading_logger.info("健康检查被用户中断")
    except Exception as e:
        trading_logger.error(f"健康检查执行异常: {e}", exc_info=True)


if __name__ == "__main__":
    main() 