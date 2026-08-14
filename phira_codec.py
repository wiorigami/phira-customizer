#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
phira_codec.py —— Phira 资源文件加解密器（单文件，无第三方依赖除 zstandard）

Copyright (C) 2026 phira-res-codec contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

逆向自开源音游 Phira（https://github.com/TeamFlos/phira）的内置资源格式。

Phira 的 `assets/res` 文件不是对称加密，而是：
    磁盘文件 = 8字节块变换( zstd(原始数据) + 填充 )

全程无密钥、可逆。本脚本同时提供加密与解密两个方向，可处理任意类型的文件
（图片 / 音频 / 谱面等），也可作为库导入使用。

依赖:  pip install zstandard

命令行用法:
    python3 phira_codec.py encrypt <输入> <输出>   # 加密成 Phira 资源格式
    python3 phira_codec.py decrypt <输入> <输出>   # 解密 Phira 资源

    输入/输出可为文件或目录；目录会递归处理（自动跳过 .yml，因为它是明文）。

库用法:
    from phira_codec import phira_encrypt, phira_decrypt
    enc = phira_encrypt(open("image.png", "rb").read())
    raw = phira_decrypt(enc)
"""

import argparse
import os
import sys

try:
    import zstandard as zstd
except ImportError:
    sys.exit("缺少依赖: 请先运行  pip install zstandard")


# ---------------------------------------------------------------------------
# 8 字节块变换（加密 = 置换 + 差分；解密为逆变换）
# ---------------------------------------------------------------------------

def _perm(v):
    """位逆序置换: 交换 (1,4) 与 (3,6)。"""
    v[1], v[4] = v[4], v[1]
    v[3], v[6] = v[6], v[3]


def decrypt_block(blk: bytes) -> bytes:
    """解密一个 8 字节块（磁盘密文 -> zstd 明文）。"""
    v = list(blk)
    v[1], v[4] = v[4], v[1]
    v[2], v[6] = v[6], v[2]
    _perm(v)
    for i in range(0, 8, 2):
        v[i | 1] = (v[i | 1] - v[i]) & 0xFF
    for i in range(0, 8, 4):
        v[i | 2] = (v[i | 2] - v[i]) & 0xFF
        v[i | 3] = (v[i | 3] - v[i | 1]) & 0xFF
    v[4] = (v[4] - v[0]) & 0xFF
    v[5] = (v[5] - v[1]) & 0xFF
    v[6] = (v[6] - v[2]) & 0xFF
    v[7] = (v[7] - v[3]) & 0xFF
    v[3], v[5] = v[5], v[3]
    return bytes(v)


def encrypt_block(blk: bytes) -> bytes:
    """加密一个 8 字节块（zstd 明文 -> 磁盘密文），为 decrypt_block 的逆。"""
    v = list(blk)
    v[3], v[5] = v[5], v[3]
    v[4] = (v[4] + v[0]) & 0xFF
    v[5] = (v[5] + v[1]) & 0xFF
    v[6] = (v[6] + v[2]) & 0xFF
    v[7] = (v[7] + v[3]) & 0xFF
    for i in (0, 4):
        v[i | 2] = (v[i | 2] + v[i]) & 0xFF
        v[i | 3] = (v[i | 3] + v[i | 1]) & 0xFF
    for i in range(0, 8, 2):
        v[i | 1] = (v[i | 1] + v[i]) & 0xFF
    _perm(v)
    v[1], v[4] = v[4], v[1]
    v[2], v[6] = v[6], v[2]
    return bytes(v)


def _transform(data: bytes, fn) -> bytes:
    """对整份数据按 8 字节块应用 fn（不足 8 字节的尾部忽略）。"""
    n = len(data) // 8 * 8
    out = bytearray(data[:n])
    for i in range(n // 8):
        out[i * 8:(i + 1) * 8] = fn(out[i * 8:(i + 1) * 8])
    return bytes(out)


# ---------------------------------------------------------------------------
# 文件级加解密
# ---------------------------------------------------------------------------

def phira_decrypt(data: bytes) -> bytes:
    """完整解密: 块逆变换 + 尾部截断 + zstd 解压 -> 原始文件字节。"""
    n = len(data)
    out = _transform(data, decrypt_block)
    if n >= 8:
        last_byte = out[n - 1]
        new_size = n + last_byte - 8   # 截断公式：zstd 帧长度 = n + 末字节 - 8
        if 0 < new_size <= n:
            out = out[:new_size]
    reader = zstd.ZstdDecompressor().stream_reader(out)
    try:
        return reader.read()
    finally:
        reader.close()


def phira_encrypt(raw: bytes, level: int = 3) -> bytes:
    """完整加密: zstd 压缩 + 填充 + 块变换 -> 磁盘文件字节。

    填充规则: pad = (8 - L%8) % 8（L%8==0 时 pad=8），填充字节值 = 8-pad
    （pad=8 时为 0），使变换后末字节恰好满足解密的截断公式。
    """
    cctx = zstd.ZstdCompressor(level=level, write_content_size=False,
                               write_checksum=False, write_dict_id=False)
    z = cctx.compress(raw)
    L = len(z)
    pad = (8 - L % 8) % 8
    if pad == 0:
        pad = 8
    val = (8 - pad) & 0xFF
    padded = z + bytes([val]) * pad
    return _transform(padded, encrypt_block)


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def _walk(path):
    """目录递归 / 单文件，均跳过 .yml（Phira 的 info.yml 为明文）。"""
    if os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for name in files:
                if name.endswith(".yml"):
                    continue
                full = os.path.join(root, name)
                yield os.path.relpath(full, path), full
    else:
        yield os.path.basename(path), path


def _resolve_out(rel, out_arg, is_dir_input):
    if is_dir_input or os.path.isdir(out_arg) or out_arg.endswith(os.sep):
        return os.path.join(out_arg, rel)
    return out_arg


def main():
    ap = argparse.ArgumentParser(description="Phira 资源文件加解密器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_enc = sub.add_parser("encrypt", help="加密成 Phira 资源格式")
    p_enc.add_argument("input")
    p_enc.add_argument("output")
    p_enc.add_argument("--level", type=int, default=3, help="zstd 压缩级别（默认 3）")

    p_dec = sub.add_parser("decrypt", help="解密 Phira 资源")
    p_dec.add_argument("input")
    p_dec.add_argument("output")

    args = ap.parse_args()
    is_dir = os.path.isdir(args.input)
    for rel, full in _walk(args.input):
        out = _resolve_out(rel, args.output, is_dir)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        data = open(full, "rb").read()
        result = phira_encrypt(data, args.level) if args.cmd == "encrypt" else phira_decrypt(data)
        open(out, "wb").write(result)
        print(f"{'加密' if args.cmd == 'encrypt' else '解密'}: {full} -> {out} ({len(result)} 字节)")


if __name__ == "__main__":
    main()
