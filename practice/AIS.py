#!/usr/bin/env python3                                                             #适配Linux
import argparse                                                                    #解析命令行
import csv                                                                         #解析CSV文件
import io                                                                          #提供内存文件对象
import os                                                                          #文件目录操作
import re                                                                          #匹配、查找、替换文本
import sys                                                                         #解释器交互
import time                                                                        #时控
import urllib.error                                                                #http请求
import urllib.request
from datetime import datetime, timedelta, timezone                                 #处理时间窗口、文件修改时间

_UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}   #全局字典


def _parse_size(text: str) -> int:                                                 #字符串转字节
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?", text.strip().upper())
    if not m:
        raise ValueError(f"无法解析大小字符串: {text!r}")
    return int(float(m.group(1)) * _UNITS[m.group(2) or "B"])


def _format_size(n: int) -> str:                                                   #字节转字符串
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def _now() -> datetime:                                                            #获取UTC时间
    return datetime.now(timezone.utc)


def _env_arg(p, flag, env, default, help_text, kind=str):                          #添加命令行参数，默认值优先从环境变量读取
    p.add_argument(flag, type=kind, default=kind(os.environ.get(env, default)), help=help_text)


def _env_flag(p, flag, env, help_text):                                            #处理布尔开关
    on = os.environ.get(env, "").lower() in ("1", "true", "yes")
    p.add_argument(flag, action="store_true", default=on, help=help_text)


def cmd_log_inspect(args) -> int:                                                  #功能一  日志巡检
    if not os.path.isdir(args.log_dir):                                            #检查日志目录是否存在
        print(f"[错误] 日志目录不存在或不是目录: {args.log_dir}", file=sys.stderr)
        return 1

    cutoff = _now() - timedelta(minutes=args.window)                               #计算时间窗口时间
    files = []
    try:                                                                           
        for entry in os.scandir(args.log_dir):                                     #遍历日志目录
            if not entry.is_file(follow_symlinks=False):
                continue
            try:
                mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            except OSError as e:
                print(f"[警告] 跳过文件状态读取失败: {entry.path} ({e})", file=sys.stderr)
                continue
            if mtime >= cutoff:
                files.append(entry.path)
    except PermissionError as e:                                                   
        print(f"[错误] 无权限访问日志目录: {args.log_dir} ({e})", file=sys.stderr)
        return 1

    if not files:
        print(f"[信息] 目录下无最近 {args.window} 分钟内修改的日志文件。")
        return 0

    total_error = total_warn = 0
    details = []
    for fpath in files:
        err = warn = 0
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:                 #逐行读取日志
                for line in f:
                    upper = line.upper()
                    err += upper.count("ERROR")
                    warn += upper.count("WARN")
        except OSError as e:
            print(f"[警告] 无法读取文件，跳过: {fpath} ({e})", file=sys.stderr)
            continue
        total_error += err
        total_warn += warn
        if err or warn:
            details.append(f"    {os.path.basename(fpath)}: ERROR={err}, WARN={warn}")

    alerts = []                                                                              
    if total_error > args.error_threshold:                                                  #生成告警信息
        alerts.append(f"[告警] ERROR 次数 {total_error} 超过阈值 {args.error_threshold}")
    if total_warn > args.warn_threshold:
        alerts.append(f"[告警] WARN 次数 {total_warn} 超过阈值 {args.warn_threshold}")

    sep = "=" * 60
    lines = [                                                                              #输出报告
        sep,
        f"日志巡检报告 — {args.log_dir}",
        f"  时间窗口: 最近 {args.window} 分钟",
        f"  ERROR: {total_error} / 阈值 {args.error_threshold}",
        f"  WARN: {total_warn} / 阈值 {args.warn_threshold}",
        f"  检查文件数: {len(files)}",
        "-" * 60,
    ]
    lines.extend(details)
    if alerts:
        lines.extend(["-" * 60, *alerts])
    lines.append(sep)

    output = "\n".join(lines)
    print(output)
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output + "\n")
        except OSError as e:
            print(f"[错误] 写入报告文件失败: {args.output} ({e})", file=sys.stderr)
            return 1
    return 1 if alerts else 0


def cmd_health_check(args) -> int:                                                  #功能二  健康检查
    urls = _resolve_services(args.services, args.services_file)                     #获取服务地址列表
    if not urls:
        print("[错误] 未提供任何服务地址，请通过 --services 或 --services-file 指定。", file=sys.stderr)
        return 1

    method = args.method.upper()
    rows = []
    for raw in urls:                                                               #循环每个地址
        url = raw.strip()
        if "://" not in url:
            url = "http://" + url

        last_error, ok = "", False
        for attempt in range(1, args.retries + 1):                                 #尝试请求
            try:
                req = urllib.request.Request(url, method=method)
                with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                    if 200 <= resp.status < 400:
                        ok = True
                        break
                    last_error = f"HTTP {resp.status}"
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code} {e.reason}"
            except urllib.error.URLError as e:
                last_error = str(e.reason)
            except (TimeoutError, OSError):
                last_error = f"超时 ({args.timeout}s)"
            except Exception as e:                                                  #捕获异常后会把原因存到last_error
                last_error = f"未知异常: {e}"
            if attempt < args.retries:
                time.sleep(1)  # 重试间隔 1s，避免瞬时压力

        rows.append((url, "正常" if ok else "异常", "" if ok else last_error))      #统计结果

    sep = "-" * 60
    print("\n服务健康检查报告")
    print(sep)
    print(f"{'服务地址':<45} {'状态':<6} {'原因'}")
    print(sep)
    abnormal = 0
    for url, status, reason in rows:
        display = url if len(url) <= 44 else url[:41] + "..."
        print(f"{display:<45} {status:<6}" + (f" {reason}" if reason else ""))
        if status == "异常":
            abnormal += 1
    print(sep)
    print(f"总计: {len(rows)} 个服务, 正常 {len(rows) - abnormal} 个, 异常 {abnormal} 个")
    return 1 if abnormal else 0


def _resolve_services(services_str, services_file) -> list[str]:             #会先尝试用CSV解析服务文件，如果失败则按纯文本读取
    urls = []
    if services_str:
        urls += [s.strip() for s in services_str.split(",") if s.strip()]
    if services_file:
        try:
            with open(services_file, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            print(f"[警告] 无法读取服务文件: {services_file} ({e})", file=sys.stderr)
            return urls
        try:
            rows = list(csv.reader(io.StringIO(content)))
            if rows and rows[0][0].strip().lower() in ("url", "地址", "service", "service_url"):
                rows = rows[1:]
            urls += [r[0].strip() for r in rows if r and r[0].strip()]
        except Exception:
            urls += [line.strip() for line in content.splitlines()
                     if line.strip() and not line.strip().startswith("#")]
    return list(dict.fromkeys(urls))                                        #去重


def cmd_disk_cleanup(args) -> int:                                          #功能三 磁盘清理
    if not os.path.isdir(args.dir):                                         #依旧检查目录
        print(f"[错误] 目录不存在或不是目录: {args.dir}", file=sys.stderr)
        return 1

    min_age_dt = None
    if args.min_age:                                                        #解析最小文件保留时间
        m = re.fullmatch(r"(\d+)([mhd])", args.min_age)
        if not m:
            print(f"[错误] 无法解析 --min-age: {args.min_age!r}，格式应为 30m/1h/2d", file=sys.stderr)
            return 1
        minutes = int(m.group(1)) * {"m": 1, "h": 60, "d": 1440}[m.group(2)]
        min_age_dt = _now() - timedelta(minutes=minutes)

    total_size = 0
    candidates = []
    try:
        for dirpath, _, filenames in os.walk(args.dir):                      #oswalk会遍历目录，在计算大小的同时，收集可清理的文件
            for fn in filenames:
                fpath = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fpath)
                except OSError:
                    continue
                total_size += st.st_size
                if min_age_dt is None or datetime.fromtimestamp(st.st_mtime, tz=timezone.utc) <= min_age_dt:
                    candidates.append((st.st_mtime, fpath, st.st_size))
    except PermissionError as e:
        print(f"[错误] 无权限遍历目录: {args.dir} ({e})", file=sys.stderr)
        return 1

    mode = "演练" if args.dry_run else "执行"
    print(f"\n[{mode}] 目录: {args.dir}")
    print(f"[{mode}] 当前占用: {_format_size(total_size)} / 阈值: {_format_size(args.threshold_bytes)}")

    if total_size <= args.threshold_bytes:
        print(f"[{mode}] 当前占用未超过阈值，无需清理。")
        return 0

    need_free = total_size - args.threshold_bytes
    print(f"[{mode}] 需释放: {_format_size(need_free)}")

    candidates.sort(key=lambda x: x[0])                                     #按修改时间升序排序，最旧的文件优先删除
    freed = deleted = skipped = 0
    for mtime, fpath, fsize in candidates:
        if freed >= need_free:                                              #如果已经释放足够空间，提前停止删除
            break
        if args.dry_run:
            when = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            print(f"  [演练] 将删除: {fpath} ({_format_size(fsize)}, 修改于 {when})")             #演练模式只会把“需要删除的文件”打印出来，不会真的删除
            freed += fsize
            deleted += 1
            continue
        try:
            os.remove(fpath)
            freed += fsize
            deleted += 1
        except OSError as e:
            print(f"  [警告] 无法删除: {fpath} ({e})", file=sys.stderr)
            skipped += 1

    print(f"[{mode}] 完成: 释放 {_format_size(freed)}，删除 {deleted} 个，跳过 {skipped} 个。"
          + ("演练模式，未执行实际删除" if args.dry_run else "执行模式"))
    if not args.dry_run and freed < need_free:
        remaining = total_size - freed
        print(f"[注意] 已清理完毕，但仍超阈值 {_format_size(remaining - args.threshold_bytes)}。", file=sys.stderr)
        return 1
    return 0


def _build_parser():                                                                            #构建命令行解析器
    parser = argparse.ArgumentParser(description="AIS.py — 运维工具箱")
    sub = parser.add_subparsers(dest="command", required=True, title="子命令")

    p_log = sub.add_parser("log-inspect", help="日志巡检")
    _env_arg(p_log, "--log-dir", "LOG_DIR", "/var/log", "日志目录路径")
    _env_arg(p_log, "--window", "LOG_WINDOW", "60", "时间窗口（分钟）", kind=int)
    _env_arg(p_log, "--error-threshold", "LOG_ERROR_THRESHOLD", "10", "ERROR 告警阈值", kind=int)
    _env_arg(p_log, "--warn-threshold", "LOG_WARN_THRESHOLD", "50", "WARN 告警阈值", kind=int)
    _env_arg(p_log, "--output", "LOG_OUTPUT", "", "告警输出文件（默认 stdout）")

    p_health = sub.add_parser("health-check", help="服务健康检查")
    _env_arg(p_health, "--services", "HEALTH_SERVICES", "", "服务 URL 列表，逗号分隔")
    _env_arg(p_health, "--services-file", "HEALTH_SERVICES_FILE", "", "服务地址文件（CSV 或每行一个）")
    _env_arg(p_health, "--retries", "HEALTH_RETRIES", "3", "失败重试次数", kind=int)
    _env_arg(p_health, "--timeout", "HEALTH_TIMEOUT", "5", "请求超时秒数", kind=int)
    _env_arg(p_health, "--method", "HEALTH_METHOD", "HEAD", "HTTP 方法 HEAD/GET")

    p_disk = sub.add_parser("disk-cleanup", help="磁盘清理")
    _env_arg(p_disk, "--dir", "CLEANUP_DIR", "/tmp", "目标目录")
    _env_arg(p_disk, "--threshold", "CLEANUP_THRESHOLD", "1GB", "占用阈值，支持 B/KB/MB/GB/TB")
    _env_flag(p_disk, "--dry-run", "CLEANUP_DRY_RUN", "演练模式，只打印不真删")
    _env_arg(p_disk, "--min-age", "CLEANUP_MIN_AGE", "", "最小文件保留时间，如 30m/1h/2d")

    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "disk-cleanup":
        try:
            args.threshold_bytes = _parse_size(args.threshold)
        except ValueError as e:
            print(f"[错误] 阈值参数解析失败: {e}", file=sys.stderr)
            return 1

    dispatch = {
        "log-inspect": cmd_log_inspect,
        "health-check": cmd_health_check,
        "disk-cleanup": cmd_disk_cleanup,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
