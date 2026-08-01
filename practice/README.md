# AIS 运维工具箱

一个用 Python 3 编写的轻量运维脚本，包含日志巡检、服务健康检查和磁盘清理三个功能。脚本不依赖第三方库，适用于学习和小型生产环境。

## 功能

| 子命令 | 功能 |
|---|---|
| `log-inspect` | 统计最近 N 分钟内日志中的 ERROR / WARN 次数，超过阈值输出告警 |
| `health-check` | 对一组服务地址做健康检查，失败自动重试，输出健康报告 |
| `disk-cleanup` | 目录超过阈值时按修改时间从旧到新清理文件，支持演练/执行模式 |

## 环境要求

- Python 3.8+
- Windows / Linux / macOS
- 无需安装第三方包

## 快速开始

```powershell
# 日志巡检：检查最近 30 分钟的日志
python AIS.py log-inspect --log-dir D:\logs --window 30

# 服务健康检查
python AIS.py health-check --services https://yourservice.com,https://api.yourservice.com

# 磁盘清理：先演练，不真正删除
python AIS.py disk-cleanup --dir D:\cache --threshold 500MB --dry-run
```

Linux 下使用 `python3` 代替 `python`：

```bash
python3 AIS.py log-inspect --log-dir /var/log/nginx --window 60
```

## 配置方式

每个参数都支持命令行参数和环境变量两种配置方式：

```powershell
$env:LOG_DIR = "D:\logs"
$env:LOG_WINDOW = "30"
python AIS.py log-inspect
```

参数优先级：命令行参数 > 环境变量 > 默认值。

详细参数、退出码和常见错误处理见 [AIS_MANUAL.md](AIS_MANUAL.md)。

## 测试

```powershell
python test_devops_tool.py
```

测试覆盖大小解析边界、日志巡检、磁盘清理、演练模式和错误处理。

## 许可证

[MIT License](LICENSE)
