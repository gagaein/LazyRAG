# Mac 本地构建、上传依赖与安装验证

适用于 **Apple Silicon Mac（M 系列，ARM64）**。在 Mac 获取本轮代码后，按“构建 → 本地验证 → 上传 RAG → 云端下载验证 → 安装试用”的顺序执行。下列命令均在 **LazyMind 仓库根目录**运行。

安装包包含基础 Python、聊天和共用依赖；RAG 专用依赖独立生成 ZIP，用户在应用内按需安装。Workflow 演示案例在首次启动 warmup 时自动下载。两者是不同的资源、不同的下载时机。

## 后续交付平台与实施交接

目标发布平台为 **Windows x64 一个版本、Mac ARM64 与 Mac Intel x64 两个架构版本**。ARM64 继续按第 1～8 节操作，Intel 原生构建使用第 9 节新入口（本机没有 Intel 真机，尚待原生验收）。第二轮瘦身实现与平台验收记录见 [第二轮开发交接计划](../docs/development/desktop-package-size-next-phase.md)。

## 0. 换电脑或交给同事打包：先确认架构

在同事的 Mac 原生终端运行：

```bash
uname -m
node -p process.arch
sw_vers -productVersion
```

| 目标电脑 | 架构 | 当前流程 |
| --- | --- | --- |
| M 系列 Mac | `arm64` | 本文第 1～8 节可用；不同代 M 芯片无需分别打包 |
| Intel Mac | `x86_64`，Node 显示 `x64` | 使用第 9 节原生 x64 入口，生成 Intel 应用和 `darwin-amd64` RAG 包；真机验收待完成 |

**按目标架构选择入口，并在对应原生 Mac 上构建。** ARM64 使用 `make desktop-darwin-arm64`，Intel 使用 `make desktop-darwin-x64`。脚本检查宿主、Node、Go 和 Python 架构，拒绝 Rosetta 或交叉混用；内部共用流程按目标选择飞书 CLI、manifest、Electron 和输出路径。不能把 ARM64 ZIP 改名为 x64。

CPU 架构与 macOS 版本是两项独立要求。本次 ARM64 构建使用的 `scipy==1.17.1` wheel 标记为 `macosx_14_0_arm64`，因此不能声称支持 macOS 13 及更旧系统；这也不代表已验证所有 macOS 14+ 版本。若需要兼容更旧系统，要另行约束依赖版本、检查原生库最低系统版本并在目标系统实测。

### 交接给另一台机器的内容

1. **完整的同一代码版本**，包括本轮 Mac 修复：构建时将 runtime 暂移出未签名 `.app` 后拆包；验证脚本和 runtime-manager 将 Numba 缓存写到应用外。只复制本文或只拉取旧的 `7587bcb7` 不包含这些本地修复。
2. 主仓库记录的 LazyLLM 子模块版本，按第 1 节初始化；不要复制开发者的 `.venv`、`node_modules` 或旧 build 目录。
3. ModelScope 数据集位置，以及需要的签名方式。ad-hoc ZIP 可用于本地测试；Developer ID/公证构建需要那台机器自己的证书和发布配置，不把证书或密钥放进 Git。
4. 构建完成交回：应用 ZIP/DMG、同次 RAG ZIP、catalog、SHA256SUMS、本地/云端验证报告和构建日志。即使同一提交重新解析依赖，也不能默认沿用另一台机器的组件。

如果修复尚未推送，可在原构建机仓库根目录导出已跟踪文件的修改补丁，并通过文件传输交给同事：

```bash
# 原构建机：记录基线并导出本地修改（输出到仓库外）
git rev-parse HEAD > ../lazymind-mac-build-base.txt
git diff --binary HEAD -- desktop/INSTALL.zh-CN.md \
  desktop/electron/electron-builder.config.cjs \
  desktop/scripts/verify-python-components.py \
  local/local-runtime-manager/runtime_env.go \
  local/local-runtime-manager/runtime_env_test.go \
  docs/development/desktop-package-size-reduction.md \
  > ../lazymind-mac-build.patch
```

同事先检出记录的基线，然后执行 `git apply --check /path/to/lazymind-mac-build.patch`，确认成功后执行 `git apply /path/to/lazymind-mac-build.patch`。如果这些修改已经提交并推送，直接检出包含修复的提交，不要重复应用补丁。

## 1. 准备构建环境和代码

需要 Xcode Command Line Tools、Git、make、Node.js 20、pnpm 10、Go 1.25 或更新的兼容工具链，以及 uv。与仓库 CI 保持一致可减少环境差异；Python 3.11.15 由构建脚本通过 uv 准备，不需要手动安装 Python 依赖。桌面构建不需要 Docker。

```bash
uname -m                  # 必须是 arm64；不要在 Rosetta 的 x86_64 终端中构建
xcode-select -p            # 未安装时先执行 xcode-select --install
git --version
make --version
node --version            # 使用 Node.js 20
node -p process.arch       # 应为 arm64
pnpm --version            # 使用 pnpm 10
go version
uv --version
```

新电脑首次获取代码（本次分支在个人仓库 `CarlosShaoting/LazyRAG`，本机命名为 `upstream` 的官方仓库没有此分支）：

```bash
git clone --branch cst/installer_opt --single-branch \
  https://github.com/CarlosShaoting/LazyRAG.git LazyMind-installer-opt
cd LazyMind-installer-opt
git submodule update --init algorithm/lazyllm
git rev-parse HEAD
git submodule status algorithm/lazyllm
```

已有独立构建仓库时，先确认工作区改动已妥善保存，再更新当前分支：

```bash
git pull --ff-only
git submodule update --init algorithm/lazyllm
git status --short
```

按第 0 节确认 Mac 修复已包含在提交中，或应用交接补丁。建议用独立克隆做构建，避免切换同事正在开发且有未提交修改的工作区。

**不要把 `algorithm/lazyllm` 子模块指针提交到 LazyMind。** 本轮不要求修改 LazyLLM 源码，也不要求修改 Skill。上面的 submodule 命令是在 Mac 获取主仓库记录的源码版本；不要用另一台机器未提交的旧检出替代。

## 2. 选择一种打包方式

先在当前终端明确开启本轮优化，指定用户已在使用的 ModelScope 目录：

```bash
export LAZYMIND_DESKTOP_PRUNE_PYTHON=true
export LAZYMIND_DESKTOP_DEFER_PYTHON=true
export LAZYMIND_DESKTOP_DEFER_HISTORY=true
export LAZYMIND_PYTHON_COMPONENT_BASE_URL='https://modelscope.cn/datasets/CarlosShaoting/lazymind-cst/resolve/master/'
export LAZYMIND_RELEASE_BUILD=false
# 可选：纯 Python 相同依赖共享；默认 false，仅审计不移动
export LAZYMIND_DESKTOP_SHARE_PYTHON=true
```

`LAZYMIND_RELEASE_BUILD=false` 使用本地源码构建方式，随应用带上主仓库记录的 LazyLLM 源码。本地测试不需要创建 release tag。

**自己先测试：选择 ZIP。** 不需要 Developer ID 证书，使用 ad-hoc 签名：

```bash
LAZYMIND_DESKTOP_PACKAGE_KIND=zip \
LAZYMIND_DESKTOP_SIGNING_MODE=adhoc \
make desktop-darwin-arm64
```

需要保存完整构建日志时，可用下面命令替代上面的构建命令；`pipefail` 确保构建失败不会被 `tee` 掩盖：

```bash
mkdir -p desktop/dist/build-logs
set -o pipefail
LAZYMIND_DESKTOP_PACKAGE_KIND=zip \
LAZYMIND_DESKTOP_SIGNING_MODE=adhoc \
make desktop-darwin-arm64 2>&1 | tee desktop/dist/build-logs/build-mac-arm64.log
```

脚本依次下载并校验飞书 CLI、编译 Go 服务、构建前端、安装 Python 3.11.15 及依赖、裁剪 Python、准备内置资源和案例下载描述、组装 Electron、拆出 RAG、签名并压缩应用。首次构建需要联网且下载较多；看到依赖安装完成不代表最终打包完成。结束时必须返回退出码 0，且打印 `.app` 和 ZIP/DMG 路径。

**已有 Developer ID Application 证书：可以选择签名 DMG。** 先确认登录钥匙串中的身份，再构建：

```bash
security find-identity -v -p codesigning
make desktop-darwin-arm64-dmg
```

本地 DMG 命令执行 Developer ID 签名，但**不自动提交 Apple 公证**。正式发布的签名/公证流程见 [Desktop README 的 macOS signed DMG](README.md#macos-signed-dmg)。ad-hoc ZIP 用于本机/内部验证，不代表已经完成正式分发验证。

两种方式选一种即可。切换 ZIP/DMG、签名身份或重新构建后，需要使用新构建配套的 RAG ZIP；不要把前一次的组件默认当作新安装包的配套文件。

## 3. 找到安装包与本次 RAG 组件

| 文件/目录 | 用途 |
| --- | --- |
| `desktop/dist/mac-arm64/LazyMind.app` | 本次完整应用，可在本机直接启动 |
| `desktop/dist/LazyMind-darwin-arm64.zip` | 选择 ZIP 构建时的应用分发包 |
| `desktop/dist/LazyMind-macos-arm64.dmg` | 选择 DMG 构建时的应用分发包 |
| `desktop/dist/python-components/darwin-arm64/lazymind-python-rag-darwin-arm64-cp311-<revision>.zip` | **需要上传到 ModelScope 的 Mac RAG 组件** |
| 同目录的 `python-components.json`、`SHA256SUMS` | 配套清单和校验信息，留档即可 |

目录可能留有旧构建的 ZIP。以下命令对比最终 `.app` 与输出 catalog，并打印**本次唯一应该上传的文件名、默认 URL 和 SHA-256**：

```bash
node <<'NODE'
const fs = require('node:fs');
const dir = 'desktop/dist/python-components/darwin-arm64';
const app = JSON.parse(fs.readFileSync('desktop/dist/mac-arm64/LazyMind.app/Contents/Resources/runtime/config/python-components.json', 'utf8')).components.rag;
const out = JSON.parse(fs.readFileSync(`${dir}/python-components.json`, 'utf8')).components.rag;
for (const key of ['filename', 'revision', 'baseFingerprint', 'sha256', 'platform', 'arch', 'pythonAbi', 'url']) {
  if (app[key] !== out[key]) throw new Error(`安装包与组件不匹配：${key}`);
}
if (out.platform !== 'darwin' || out.arch !== 'arm64') throw new Error('不是 Mac ARM64 组件');
console.log(`上传文件：${dir}/${out.filename}`);
console.log(`下载地址：${out.url}`);
console.log(`大小：${(out.sizeBytes / 1024 / 1024).toFixed(2)} MiB`);
console.log(`SHA-256：${out.sha256}`);
NODE

(cd desktop/dist/python-components/darwin-arm64 && shasum -a 256 -c SHA256SUMS)
```

**安装包与组件必须来自同一次构建。** Mac 组件不能替代已上传的 Windows 组件；本次不发布 Linux，无需上传 Linux 组件。

## 4. 上传前，验证本地组件

Mac 在 Electron 组装 `.app` 时才拆出 RAG；Developer ID 模式还会先签组件内的原生库。请使用**最终 `.app` 内的 Python 和 catalog**，不要用 `desktop/build/darwin-arm64/runtime` 中尚未拆包的中间环境，也不要手动再对已签名 `.app` 运行拆包脚本。

```bash
MAC_RUNTIME="$(pwd)/desktop/dist/mac-arm64/LazyMind.app/Contents/Resources/runtime"
MAC_PYTHON="$MAC_RUNTIME/deps/python/algorithm/bin/python"

"$MAC_PYTHON" -B desktop/scripts/verify-python-components.py \
  --runtime "$MAC_RUNTIME" \
  --bundle-dir "$(pwd)/desktop/dist/python-components/darwin-arm64" \
  --report "$(pwd)/desktop/dist/component-check/darwin-arm64/local-report.json"

# 验证导入没有向应用内写缓存、破坏签名
codesign --verify --deep --strict --verbose=2 desktop/dist/mac-arm64/LazyMind.app
```

成功应返回退出码 0，并且报告为 `"passed": true`。检查包括基础依赖导入、RAG ZIP 校验/解压、RAG 导入、Milvus 写入/落盘/重启后检索/删除集合。测试使用临时数据库，保留分阶段日志，不修改用户知识库。

若报错，先保留报告、日志和本次组件清单定位问题；不要将失败记录当作功能验收通过。当前已有 Windows Milvus `WinError 183` 问题记录，Mac 是否通过以这台 Mac 的实际结果为准。

## 5. 手动上传 ModelScope

1. 登录 ModelScope，打开数据集 [CarlosShaoting/lazymind-cst](https://modelscope.cn/datasets/CarlosShaoting/lazymind-cst)。
2. 将第 3 步打印的 **Mac RAG 原始 ZIP** 上传到 **`master` 分支根目录**。
3. 保持文件名和 ZIP 内容不变，不解压后上传、不再次压缩，也不要把整个组件目录套成另一个 ZIP。
4. `python-components.json`、`SHA256SUMS` 和测试报告本地留档；应用运行不要求将它们上传。应用 ZIP/DMG 是给用户安装的另一个分发文件，不要把它填写为 RAG 下载地址。
5. 已上传的 Windows RAG 文件保留原样。现有 FFmpeg 和 Workflow 五案例包已经在云端，本轮没有更新这些内容，无需重复上传。

默认完整链接为：

```text
https://modelscope.cn/datasets/CarlosShaoting/lazymind-cst/resolve/master/<第3步打印的Mac组件文件名>
```

链接必须无需登录即可直接下载 ZIP。采用默认目录且文件名不变时，**上传后不需要改代码或重新打包**；该链接已经写入本次应用。若换了托管位置，可在应用的 RAG 安装输入框填写完整 HTTPS 地址，但下载的内容仍必须与本次 catalog 的 checksum 一致。

## 6. 验证刚上传的云端文件

继续使用第 4 步的两个变量，去掉 `--bundle-dir` 后，脚本会实际下载 catalog 中的 ModelScope URL：

```bash
"$MAC_PYTHON" -B desktop/scripts/verify-python-components.py \
  --runtime "$MAC_RUNTIME" \
  --report "$(pwd)/desktop/dist/component-check/darwin-arm64/cloud-report.json"

codesign --verify --deep --strict --verbose=2 desktop/dist/mac-arm64/LazyMind.app
```

再次确认退出码 0、`passed=true`。这一步验证云端文件与本次安装包清单相符，而不只是网页能打开；测试会下载完整组件。

## 7. 安装应用并按实际用户流程测试

先关闭已有 LazyMind Desktop/Local 实例，避免同一数据目录和端口冲突。ZIP 解压后将 `LazyMind.app` 放到“应用程序”；DMG 则打开后拖入“应用程序”。也可以先直接启动本次构建目录中的应用：

```bash
open desktop/dist/mac-arm64/LazyMind.app
```

按以下顺序检查：

1. 首次启动等待 warmup。Workflow 演示案例应自动下载、校验和导入；核对五个案例及图片/PPT 产物可打开。
2. 尚未安装 RAG 时，普通聊天、模型配置、常用附件功能应可使用；知识库相关操作应提示安装组件，而不是一直转圈。
3. 打开“设置 → 系统工具 → 依赖”，找到 RAG，确认默认地址是第 3 步打印的 Mac ZIP，点击安装。
4. 安装完成后点击“重启本地服务”，或退出后重新打开应用。重启前先结束正在进行的任务。
5. 新建测试知识库，上传 PDF/Word，等待解析完成，验证检索和知识问答；退出重开应用后再次检索同一份文档，并测试删除测试文档/知识库。
6. 回归普通聊天、常用 Workflow、Skill、Ark 图片/视频功能。已有同版本组件时可能直接显示已安装，不需要为了测试清除已有数据。

脚本通过只证明依赖与临时 Milvus 路径通过；界面、真实模型调用、首次 warmup、签名和安装行为仍以上述实际试用为准。

## 8. 常见问题与重新构建

| 现象 | 检查方式 |
| --- | --- |
| RAG 默认 URL 返回 404 | 对照第 3 步文件名，确认上传在 `master` 根目录且公开可读 |
| 下载后大小/SHA 或兼容性校验失败 | 上传对应 `.app` 同次构建的原始 ZIP；自定义 URL 不能绕过校验 |
| 没有生成 `darwin-arm64` 组件 | 检查构建是否完整成功、`LAZYMIND_DESKTOP_DEFER_PYTHON` 是否为 true，以及最终 `.app` 是否有 catalog |
| 验证脚本提示基础环境仍有 RAG | 检查使用的是最终 `.app` 的 Python，而不是中间 build runtime 或系统 Python |
| DMG 提示找不到签名身份 | 使用已配置 Developer ID 的钥匙串，或改用第 2 步的 ad-hoc ZIP 做本机测试 |
| macOS 提示来源/签名问题 | 区分本地 ad-hoc 包、Developer ID 签名包与已公证包；正式分发遵循现有签名/公证流程 |
| 构建拆包时弹出“应用已损坏”，随后文件消失 | 确认包含将 runtime 暂移到 `.app` 外拆包的修复；被移入废纸篓的构建产物需要重新封装 |
| 验证后签名报新增 `.nbc/.nbi` 文件 | 确认使用新版验证脚本，且 runtime-manager 设置 `NUMBA_CACHE_DIR` 到用户缓存；仅加 `-B` 不能阻止 Numba 缓存 |
| 修改代码后重新打包 | 重做第 3～6 步；按新 catalog 选择组件，不改写旧文件名来冒充新组件 |

后续若改用 GitHub 构建安装包，也要上传那次 Actions 的 `macos-python-components` 附件中配套的原始 RAG ZIP，不能默认沿用这次本地产物。详细实现、体积记录和已知问题见 [开发文档](../docs/development/desktop-package-size-reduction.md)。

## 9. Intel Mac 原生构建入口（代码已实现，真机验收待完成）

在原生 Intel Mac 上完成第 1 节依赖和源码准备：`uname -m` 应为 `x86_64`，`node -p process.arch` 为 `x64`，`go env GOHOSTARCH GOARCH` 均为 `amd64`。不要在 M 系列的 Rosetta 终端代替 Intel 真机验收。

沿用第 2 节的优化环境变量，选择一条命令：

```bash
# ad-hoc 测试 ZIP
LAZYMIND_DESKTOP_PACKAGE_KIND=zip LAZYMIND_DESKTOP_SIGNING_MODE=adhoc make desktop-darwin-x64
# 或已有 Developer ID 证书时构建 DMG
make desktop-darwin-x64-dmg
```

| 产物 | Intel 路径 |
| --- | --- |
| 应用 | `desktop/dist/mac/LazyMind.app`（electron-builder x64 默认目录名是 `mac`） |
| 应用 ZIP | `desktop/dist/LazyMind-darwin-x64.zip` |
| DMG | `desktop/dist/LazyMind-macos-x64.dmg` |
| RAG 组件目录 | `desktop/dist/python-components/darwin-amd64/` |
| 中间环境与报告 | `desktop/build/darwin-x64/` |

```bash
MAC_RUNTIME="$(pwd)/desktop/dist/mac/LazyMind.app/Contents/Resources/runtime"
MAC_PYTHON="$MAC_RUNTIME/deps/python/algorithm/bin/python"
"$MAC_PYTHON" -B desktop/scripts/verify-python-components.py \
  --runtime "$MAC_RUNTIME" \
  --bundle-dir "$(pwd)/desktop/dist/python-components/darwin-amd64" \
  --report "$(pwd)/desktop/dist/component-check/darwin-amd64/local-report.json"
codesign --verify --deep --strict desktop/dist/mac/LazyMind.app
(cd desktop/dist/python-components/darwin-amd64 && shasum -a 256 -c SHA256SUMS)
```

第 3 节 catalog 对照代码中的路径换成表内 Intel 路径，架构断言换为 `amd64`。按 catalog 打印的**实际文件名**上传原始 RAG ZIP，之后去掉 `--bundle-dir` 再做云端验证。复用同一份字体及案例资源，保留已上传的 ARM64、Windows RAG 文件。

本机已验证 Intel 飞书 CLI 原始下载的 SHA 和 Mach-O `x86_64` 架构，并测试了 Intel manifest；**没有构建/运行完整 Intel 应用**，不能据此宣称 Intel 的 Python wheels、最低系统版本、签名或业务功能已验收。需由 Intel 机器完成原生构建及第 7 节回归。

## 10. 本次 ARM64 已完成的参考结果

2026-09-20，以 `7587bcb7` 加本地 Mac 修复构建：

- RAG 文件：`lazymind-python-rag-darwin-arm64-cp311-53a1c2e770966b71.zip`。
- 大小：54,515,729 字节（51.99 MiB）；SHA-256：`f90b5c00b43943b031d698fc939c81b24d77a738e357bb541fe74d7e768fb8d1`。
- 已上传默认 ModelScope 目录；从云端实际下载后，六阶段验证全部通过，应用签名复查通过。
- 应用为本地 ad-hoc 测试包；没有完成 Developer ID/公证、全部业务界面或其他 macOS 版本验证。

这些记录用于核对本次交付，**不是另一台机器重新构建后必须得到的文件名或哈希**。重新构建仍以新应用中的 catalog 为准。

## 11. 第二轮资源、共享开关与 Windows 操作

### Python 共享和最终体积报告

`LAZYMIND_DESKTOP_SHARE_PYTHON` 默认 `false`：审计候选，不改变三个环境。设置 `true` 才共享相同内容的纯 Python wheel；GitHub workflow 的对应输入是 `share_python`。Windows 与 Intel 的原生搬迁验收完成前，发布构建可保持关闭。切换回不共享模式应执行完整干净构建，`resume` 不会恢复已移走的包。

报告位于最终 runtime 的 `config/python-sharing.json`，包含共享包、环境、实际节省字节和跳过原因；相同包不是全局暴露给所有环境，而是各环境通过相对 `.pth` 引用自己的共享目录。RAG 拆包先于共享，版本/RECORD 内容不改，catalog 继续绑定同一逻辑依赖集。

最终体积报告：`desktop/build/<目标>/final-runtime-size.json`，区分应用、解释器、各 venv、shared、外置 RAG、字体与最终压缩产物。Mac 的报告在封装后生成；Windows 在 payload 封装前统计实际展开 runtime，完成后补记 EXE/ZIP 大小。不能把展开体积直接当成安装包节省。

### 新增一次性的 PDF 字体上传

三个平台共用 [ModelScope 数据集](https://modelscope.cn/datasets/CarlosShaoting/lazymind-cst) `master` 根目录。上传 `desktop/dist/pdf-font/` 中的以下 **TTF 原文件**，不用压成 ZIP；同时保留/分发 `NotoSansSC-OFL.txt` 许可证。

- 文件名：`lazymind-pdf-NotoSansSC-a3041811a78c361b.ttf`。
- 大小：17,772,300 字节（16.95 MiB）。
- SHA-256：`a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da`。
- 上传后的目标 URL：`https://modelscope.cn/datasets/CarlosShaoting/lazymind-cst/resolve/master/lazymind-pdf-NotoSansSC-a3041811a78c361b.ttf`。

该文件在本轮交付时**尚未上传**，URL 是构建描述中的目标地址。构建不访问此 URL。上传前新桌面包首次中文 PDF 导出会提示字体下载失败；上传后可直接重试，无需重打应用。用户缓存位于 runtime 的 `deps/pdf-font/<sha>/`，第二次可离线复用，损坏缓存会重新下载。普通 PDF 阅读不触发下载，Web/Docker 静态字体保持原样。

上传后先核对真实下载字节，再在应用中验证中文可搜索 PDF、翻译导出、重启后离线导出与 Mac 签名：

```bash
curl --fail --location --proto '=https' --proto-redir '=https' \
  'https://modelscope.cn/datasets/CarlosShaoting/lazymind-cst/resolve/master/lazymind-pdf-NotoSansSC-a3041811a78c361b.ttf' \
  --output /tmp/lazymind-pdf-font-cloud.ttf
shasum -a 256 /tmp/lazymind-pdf-font-cloud.ttf
# 应与上面的完整 SHA-256 一致
```

### Windows x64 原生构建与搬迁验收

在原生 Windows PowerShell、仓库根目录，安装现有 Windows 构建要求的 Node/pnpm、Go、uv 和 Git；不用 WSL Python 代替 Windows Python。先检出同一提交并初始化 LazyLLM 子模块。

```powershell
$env:LAZYMIND_RELEASE_BUILD = 'false'
$env:LAZYMIND_DESKTOP_PRUNE_PYTHON = 'true'
$env:LAZYMIND_DESKTOP_DEFER_PYTHON = 'true'
$env:LAZYMIND_DESKTOP_DEFER_HISTORY = 'true'
# 开启共享用于原生验收；未验收的发布包可保持 false
$env:LAZYMIND_DESKTOP_SHARE_PYTHON = 'true'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop/scripts/build-windows-x64.ps1 installer
```

RAG 产物在 `desktop/dist/python-components/windows-amd64/`；字体目录同上。新构建移除 staging 中的 Mac Core 开发二进制和 LazyLLM 文档，不删除源文件。解释器别名规范化使用唯一真实捆绑 Python，先检查三个 venv 都能启动，再删除 junction，输出 `runtime/config/python-aliases.json`；异常直接停止构建。

在 Windows 上还需要实际安装 EXE 到含中文/空格路径，确认原构建路径不可用时 warmup 能完成，三个 Python 服务、登录、聊天、飞书、Skill 与 RAG 均能启动；覆盖重复启动、覆盖升级、`resume-installer` 和 `python-runtime.zip` 内容检查。本机仅做了 Windows runtime-manager 测试二进制的交叉编译，不能替代这些原生运行测试。

已有 Windows `milvus-lite==3.0` 的 `WinError 183` 尚未修复，本轮没有静默改第三方源码或旧组件校验值；显式 flush/重启持久化仍需单独验收。
