# Phira 资源编解码&编码器（phira-res-codec）

一个极简的 Python 脚本，实现 Phira（开源音游）内置资源文件的**加密与解密**。

- 单文件 `phira_codec.py`，无框架，依赖仅 `zstandard`
- 同时支持加密（把任意文件打包成 Phira 资源格式）与解密（把 Phira 资源还原为原始文件）
- 处理任意类型文件：图片、音频、谱面等
- 可作为库导入，也可命令行使用

## 原理

Phira 的 `assets/res` 文件并非对称加密，而是：

```
磁盘文件 = 8字节块变换( zstd(原始数据) + 填充 )
```

其中「8 字节块变换」为**置换 + 差分**（无密钥、可逆）：

- 交换字节 1↔4、2↔6
- 位逆序置换：交换 (1,4) 与 (3,6)
- 三层蝴蝶加减（mod 256）
- 交换字节 3↔5

解密方向做减法、加密方向做加法；尾部用「`zstd帧长度 = n + 末字节 - 8`」截断，
加密时按该公式填充。

## 安装

```bash
pip install zstandard
```

## 使用

```bash
# 加密：把文件/目录打包成 Phira 资源格式
python3 phira_codec.py encrypt 输入文件  输出文件
python3 phira_codec.py encrypt 输入目录  输出目录

# 解密：把资源加密为原始文件
python3 phira_codec.py decrypt 输入文件  输出文件
python3 phira_codec.py decrypt 输入目录  输出目录
```

作为库：

```python
from phira_codec import phira_encrypt, phira_decrypt

enc = phira_encrypt(open("image.png", "rb").read())
raw = phira_decrypt(enc)
assert raw == open("image.png", "rb").read()
```

## 说明

- 格式逆向自开源项目 [TeamFlos/phira](https://github.com/TeamFlos/phira)。
- 本项目仅提供格式的加解密实现，供学习与自制内容使用，请遵守相关规范。
- 处理目录时自动跳过 `.yml`（Phira 的 `info.yml` 是明文，不在加密范围内）。

## 许可

[GNU General Public License v3.0](LICENSE)（GPL-3.0）

---

全项目 vibe cod  
侵删
