import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { open } from "@tauri-apps/plugin-dialog";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  FolderOpen,
  Loader2,
  X,
} from "lucide-react";

type Lang = "zh-CN" | "en-US";
type StepId =
  | "language"
  | "welcome"
  | "license"
  | "path"
  | "components"
  | "migrate"
  | "install"
  | "finish";

const STEPS: StepId[] = [
  "language",
  "welcome",
  "license",
  "path",
  "components",
  "migrate",
  "install",
  "finish",
];

interface PreviousInstall {
  install_dir: string;
  version: string | null;
  user_data_dir: string | null;
}

interface ProgressEvent {
  stage: string;
  message: string;
  percent: number;
}

const LICENSE_ZH = `HakusAI 软件许可协议（摘要）

1. 本软件按「现状」提供，不提供任何明示或默示担保。
2. 你可以自由使用本软件进行个人或商业工作。
3. 未经许可不得将本软件冒充为其他产品进行再分发。
4. 使用 AI 模型时，请遵守对应服务商的条款与配额。
5. 卸载时可选择是否删除本地会话、记忆与配置数据。

完整协议见项目仓库 LICENSE 文件。`;

const LICENSE_EN = `HakusAI Software License (Summary)

1. The software is provided "as is", without warranty of any kind.
2. You may use it for personal or commercial work.
3. You may not redistribute it as a different product.
4. When using AI providers, follow their terms and quotas.
5. On uninstall you may choose whether to keep local data.

See the LICENSE file in the project repository for details.`;

const copyMap = {
  "zh-CN": {
    steps: {
      language: "语言",
      welcome: "欢迎",
      license: "许可协议",
      path: "安装位置",
      components: "组件",
      migrate: "数据迁移",
      install: "安装",
      finish: "完成",
    },
    title: "HakusAI 安装程序",
    languageTitle: "选择安装语言",
    languageLead: "安装向导与说明文字将使用此语言。",
    welcomeTitle: "欢迎使用 HakusAI",
    welcomeLead: "本向导将引导你完成安装。建议先关闭其他占用资源较多的应用。",
    features: [
      { t: "全屏启动动画", d: "启动时展示品牌启动画面，再进入应用。" },
      { t: "首次运行向导", d: "语言、模型、工作区在应用内逐步完成。" },
      { t: "自动更新", d: "正式版支持从 GitHub Releases 拉取更新。" },
      { t: "可选开机启动", d: "按需创建启动项，不强制。" },
    ],
    licenseTitle: "许可协议",
    licenseLead: "请阅读并接受协议后继续。",
    accept: "我已阅读并同意",
    pathTitle: "选择安装位置",
    pathLead: "应用将安装到以下目录。",
    browse: "浏览…",
    componentsTitle: "选择组件",
    componentsLead: "勾选需要创建的快捷方式与启动项。",
    desktop: "桌面快捷方式",
    desktopD: "在桌面创建 HakusAI 图标。",
    startMenu: "开始菜单快捷方式",
    startMenuD: "在开始菜单「程序」中创建入口。",
    startup: "开机启动",
    startupD: "登录 Windows 后自动启动（可随时在任务管理器禁用）。",
    launchAfter: "安装完成后启动 HakusAI",
    launchAfterD: "立刻打开应用进行首次配置。",
    migrateTitle: "检测到已有安装",
    migrateLead: "可以选择保留原用户数据（会话、设置、记忆）。",
    migrateKeep: "迁移/保留用户数据",
    migrateKeepD: "不会覆盖已存在的用户配置目录。",
    migrateNoneTitle: "未检测到旧版本",
    migrateNoneLead: "将执行全新安装。",
    installTitle: "正在安装",
    installLead: "请稍候，安装过程通常只需几秒到一分钟。",
    finishTitle: "安装完成",
    finishLead: "HakusAI 已成功安装到你的电脑。",
    finishNote: "下一步：打开应用后完成首次运行向导（模型 API Key 等）。",
    next: "下一步",
    back: "上一步",
    installBtn: "开始安装",
    close: "关闭",
    done: "完成",
    cancel: "取消",
    pathLabel: "安装目录",
    summaryInstall: "安装位置",
    payloadMissing: "未找到 app-payload.zip",
    installing: "安装中",
    payloadOk: "安装包已就绪",
    payloadSize: "安装包大小",
    licenseAcceptRequired: "请先勾选同意许可协议",
    welcomeBadge: "AI Workspace",
  },
  "en-US": {
    steps: {
      language: "Language",
      welcome: "Welcome",
      license: "License",
      path: "Location",
      components: "Components",
      migrate: "Data",
      install: "Install",
      finish: "Finish",
    },
    title: "HakusAI Installer",
    languageTitle: "Choose installer language",
    languageLead: "Wizard text and notes will use this language.",
    welcomeTitle: "Welcome to HakusAI",
    welcomeLead: "This wizard will guide you through installation. Close heavy apps if possible.",
    features: [
      { t: "Fullscreen splash", d: "A branded boot animation before the main UI." },
      { t: "First-run setup", d: "Language, model, and workspace are configured in-app." },
      { t: "Auto update", d: "Stable builds can update from GitHub Releases." },
      { t: "Optional autostart", d: "Create a startup entry only if you want it." },
    ],
    licenseTitle: "License agreement",
    licenseLead: "Please read and accept the agreement to continue.",
    accept: "I have read and accept",
    pathTitle: "Choose install location",
    pathLead: "HakusAI will be installed to this folder.",
    browse: "Browse…",
    componentsTitle: "Choose components",
    componentsLead: "Select the shortcuts and startup entries to create.",
    desktop: "Desktop shortcut",
    desktopD: "Create a HakusAI icon on the desktop.",
    startMenu: "Start menu shortcut",
    startMenuD: "Add HakusAI under Start → Programs.",
    startup: "Launch at startup",
    startupD: "Start automatically after sign-in (can be disabled later).",
    launchAfter: "Launch HakusAI after install",
    launchAfterD: "Open the app immediately for first-run setup.",
    migrateTitle: "Existing installation found",
    migrateLead: "You can keep previous user data (sessions, settings, memory).",
    migrateKeep: "Keep / migrate user data",
    migrateKeepD: "Does not overwrite an existing user-data directory.",
    migrateNoneTitle: "No previous version found",
    migrateNoneLead: "This will be a fresh install.",
    installTitle: "Installing",
    installLead: "Please wait. This usually takes a few seconds to a minute.",
    finishTitle: "Installation complete",
    finishLead: "HakusAI was installed successfully.",
    finishNote: "Next: complete the in-app first-run wizard (API keys, etc.).",
    next: "Next",
    back: "Back",
    installBtn: "Install",
    close: "Close",
    done: "Done",
    cancel: "Cancel",
    pathLabel: "Install folder",
    summaryInstall: "Location",
    payloadMissing: "app-payload.zip not found",
    installing: "Installing",
    payloadOk: "Payload ready",
    payloadSize: "Payload size",
    licenseAcceptRequired: "Please accept the license agreement",
    welcomeBadge: "AI Workspace",
  },
} as const;

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export default function App() {
  const [lang, setLang] = useState<Lang>("zh-CN");
  const [step, setStep] = useState<StepId>("language");
  const [installDir, setInstallDir] = useState("");
  const [prev, setPrev] = useState<PreviousInstall | null>(null);
  const [payload, setPayload] = useState<{ ok: boolean; path?: string; size_bytes?: number; message?: string } | null>(null);
  const [acceptLicense, setAcceptLicense] = useState(false);
  const [createDesktop, setCreateDesktop] = useState(true);
  const [createStartMenu, setCreateStartMenu] = useState(true);
  const [launchOnStartup, setLaunchOnStartup] = useState(false);
  const [launchAfter, setLaunchAfter] = useState(true);
  const [migrateData, setMigrateData] = useState(true);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resultDir, setResultDir] = useState<string | null>(null);

  const t = copyMap[lang];
  const stepIndex = STEPS.indexOf(step);

  const stepLabel = useCallback(
    (id: StepId) => t.steps[id],
    [t],
  );

  useEffect(() => {
    void (async () => {
      try {
        const dir = await invoke<string>("default_install_path");
        setInstallDir(dir);
      } catch {
        /* ignore */
      }
      try {
        const previous = await invoke<PreviousInstall | null>("detect_previous_install");
        setPrev(previous ?? null);
      } catch {
        /* ignore */
      }
      try {
        const status = await invoke<{ ok: boolean; path?: string; size_bytes?: number; message?: string }>("payload_status");
        setPayload(status);
      } catch (e) {
        setPayload({ ok: false, message: String(e) });
      }
    })();
  }, []);

  useEffect(() => {
    const un = listen<ProgressEvent>("install-progress", (e) => setProgress(e.payload));
    return () => {
      void un.then((f) => f());
    };
  }, []);

  const canNext = useMemo(() => {
    if (step === "language") return true;
    if (step === "welcome") return true;
    if (step === "license") return acceptLicense;
    if (step === "path") return installDir.trim().length > 0 && Boolean(payload?.ok);
    if (step === "components") return true;
    if (step === "migrate") return true;
    return false;
  }, [step, acceptLicense, installDir, payload]);

  const goNext = () => {
    if (step === "license" && !acceptLicense) {
      setError(t.licenseAcceptRequired);
      return;
    }
    setError(null);
    const i = STEPS.indexOf(step);
    if (i < STEPS.length - 1) setStep(STEPS[i + 1]);
  };

  const goBack = () => {
    setError(null);
    const i = STEPS.indexOf(step);
    if (i > 0 && step !== "install" && step !== "finish") setStep(STEPS[i - 1]);
  };

  const pickFolder = async () => {
    const selected = await open({ directory: true, multiple: false });
    if (typeof selected === "string") setInstallDir(selected);
  };

  const runInstall = async () => {
    setInstalling(true);
    setError(null);
    setProgress({ stage: "prepare", message: "…", percent: 0.01 });
    try {
      const result = await invoke<{ ok: boolean; install_dir: string; message: string }>(
        "run_install",
        {
          request: {
            install_dir: installDir,
            create_desktop_shortcut: createDesktop,
            create_start_menu: createStartMenu,
            launch_on_startup: launchOnStartup,
            launch_after_install: launchAfter,
            migrate_user_data: migrateData,
          },
        },
      );
      setResultDir(result.install_dir);
      setProgress({ stage: "done", message: result.message, percent: 1 });
      setStep("finish");
    } catch (e) {
      setError(String(e));
    } finally {
      setInstalling(false);
    }
  };

  const closeApp = async () => {
    try {
      await getCurrentWindow().close();
    } catch {
      window.close();
    }
  };

  const renderBody = () => {
    switch (step) {
      case "language":
        return (
          <>
            <h2>{t.languageTitle}</h2>
            <p className="lead">{t.languageLead}</p>
            <div className="lang-grid">
              {(
                [
                  ["zh-CN", "简体中文", "Simplified Chinese"],
                  ["en-US", "English", "Installer language"],
                ] as const
              ).map(([id, title, desc]) => (
                <button
                  key={id}
                  type="button"
                  className={`lang-card ${lang === id ? "selected" : ""}`}
                  onClick={() => setLang(id)}
                >
                  <strong>{title}</strong>
                  <span>{desc}</span>
                </button>
              ))}
            </div>
          </>
        );
      case "welcome":
        return (
          <>
            <h2>{t.welcomeTitle}</h2>
            <p className="lead">{t.welcomeLead}</p>
            <div className="welcome-hero">
              <h3>HakusAI · {t.welcomeBadge}</h3>
              <div className="feature-grid">
                {t.features.map((f) => (
                  <div className="feature" key={f.t}>
                    <strong>{f.t}</strong>
                    <span>{f.d}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        );
      case "license":
        return (
          <>
            <h2>{t.licenseTitle}</h2>
            <p className="lead">{t.licenseLead}</p>
            <div className="card license-box">{lang === "zh-CN" ? LICENSE_ZH : LICENSE_EN}</div>
            <label className="option-row" style={{ borderBottom: "none" }}>
              <input
                type="checkbox"
                checked={acceptLicense}
                onChange={(e) => setAcceptLicense(e.target.checked)}
              />
              <div className="option-copy">
                <strong>{t.accept}</strong>
              </div>
            </label>
          </>
        );
      case "path":
        return (
          <>
            <h2>{t.pathTitle}</h2>
            <p className="lead">{t.pathLead}</p>
            {payload && !payload.ok && (
              <div className="alert error">{payload.message || t.payloadMissing}</div>
            )}
            {payload?.ok && (
              <div className="alert info">
                {t.payloadOk}
                {payload.size_bytes != null ? ` · ${t.payloadSize} ${formatBytes(payload.size_bytes)}` : ""}
              </div>
            )}
            <div className="field">
              <label>{t.pathLabel}</label>
              <div className="path-row">
                <input
                  value={installDir}
                  onChange={(e) => setInstallDir(e.target.value)}
                  spellCheck={false}
                />
                <button type="button" className="btn" onClick={pickFolder}>
                  <FolderOpen size={16} style={{ verticalAlign: -3, marginRight: 6 }} />
                  {t.browse}
                </button>
              </div>
            </div>
            <div className="summary-list" style={{ marginTop: 18 }}>
              <div>
                <span>{t.summaryInstall}</span>
                <span>{installDir}</span>
              </div>
            </div>
          </>
        );
      case "components":
        return (
          <>
            <h2>{t.componentsTitle}</h2>
            <p className="lead">{t.componentsLead}</p>
            <div className="card">
              <label className="option-row">
                <input type="checkbox" checked={createDesktop} onChange={(e) => setCreateDesktop(e.target.checked)} />
                <div className="option-copy">
                  <strong>{t.desktop}</strong>
                  <span>{t.desktopD}</span>
                </div>
              </label>
              <label className="option-row">
                <input type="checkbox" checked={createStartMenu} onChange={(e) => setCreateStartMenu(e.target.checked)} />
                <div className="option-copy">
                  <strong>{t.startMenu}</strong>
                  <span>{t.startMenuD}</span>
                </div>
              </label>
              <label className="option-row">
                <input type="checkbox" checked={launchOnStartup} onChange={(e) => setLaunchOnStartup(e.target.checked)} />
                <div className="option-copy">
                  <strong>{t.startup}</strong>
                  <span>{t.startupD}</span>
                </div>
              </label>
              <label className="option-row">
                <input type="checkbox" checked={launchAfter} onChange={(e) => setLaunchAfter(e.target.checked)} />
                <div className="option-copy">
                  <strong>{t.launchAfter}</strong>
                  <span>{t.launchAfterD}</span>
                </div>
              </label>
            </div>
          </>
        );
      case "migrate":
        return (
          <>
            <h2>{prev ? t.migrateTitle : t.migrateNoneTitle}</h2>
            <p className="lead">{prev ? t.migrateLead : t.migrateNoneLead}</p>
            {prev && (
              <>
                <div className="alert warn">
                  {prev.install_dir}
                  {prev.user_data_dir ? ` · ${prev.user_data_dir}` : ""}
                </div>
                <div className="card">
                  <label className="option-row">
                    <input type="checkbox" checked={migrateData} onChange={(e) => setMigrateData(e.target.checked)} />
                    <div className="option-copy">
                      <strong>{t.migrateKeep}</strong>
                      <span>{t.migrateKeepD}</span>
                    </div>
                  </label>
                </div>
              </>
            )}
          </>
        );
      case "install":
        return (
          <>
            <h2>{t.installTitle}</h2>
            <p className="lead">{t.installLead}</p>
            {error && <div className="alert error">{error}</div>}
            <div className="progress-wrap">
              <div className="progress-track">
                <div
                  className="progress-bar"
                  style={{ width: `${Math.round((progress?.percent ?? 0) * 100)}%` }}
                />
              </div>
              <div className="stage">
                <span>
                  {progress?.message || t.installing}
                  {installing ? (
                    <>
                      {" "}
                      <span className="dots" aria-hidden>
                        <i />
                        <i />
                        <i />
                      </span>
                    </>
                  ) : null}
                </span>
                <span>{Math.round((progress?.percent ?? 0) * 100)}%</span>
              </div>
            </div>
          </>
        );
      case "finish":
        return (
          <>
            <h2>{t.finishTitle}</h2>
            <p className="lead">{t.finishLead}</p>
            <div className="alert success">
              <Check size={14} style={{ verticalAlign: -2, marginRight: 6 }} />
              {resultDir || installDir}
            </div>
            <p className="lead" style={{ marginBottom: 0 }}>
              {t.finishNote}
            </p>
          </>
        );
    }
  };

  const showFooter = step !== "install" || !installing;
  const isLastBeforeInstall = step === "migrate";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">H</div>
          <div>
            <h1>HakusAI</h1>
            <p>{t.welcomeBadge}</p>
          </div>
        </div>
        <ul className="steps">
          {STEPS.map((id, i) => (
            <li
              key={id}
              className={
                id === step ? "active" : i < STEPS.indexOf(step) ? "done" : undefined
              }
            >
              <span className="step-index">{i < STEPS.indexOf(step) ? <Check size={12} /> : i + 1}</span>
              {stepLabel(id)}
            </li>
          ))}
        </ul>
      </aside>

      <section className="main">
        <div className="titlebar" data-tauri-drag-region>
          <span className="titlebar-title">{t.title}</span>
          <div className="win-controls">
            <button type="button" className="win-btn close" onClick={closeApp} aria-label={t.close}>
              <X size={14} />
            </button>
          </div>
        </div>

        <div className="content">{renderBody()}</div>

        {showFooter && (
          <div className="footer">
            <div className="footer-actions">
              {stepIndex > 0 && step !== "finish" && (
                <button type="button" className="btn ghost" onClick={goBack} disabled={installing}>
                  <ArrowLeft size={14} style={{ verticalAlign: -2, marginRight: 6 }} />
                  {t.back}
                </button>
              )}
              {step !== "finish" && !isLastBeforeInstall && (
                <button type="button" className="btn primary" onClick={goNext} disabled={!canNext || installing}>
                  {t.next}
                  <ArrowRight size={14} style={{ verticalAlign: -2, marginLeft: 6 }} />
                </button>
              )}
              {isLastBeforeInstall && (
                <button
                  type="button"
                  className="btn primary"
                  onClick={runInstall}
                  disabled={!payload?.ok || installing}
                >
                  {installing ? <Loader2 size={14} className="spin" style={{ verticalAlign: -2, marginRight: 6 }} /> : null}
                  {t.installBtn}
                </button>
              )}
              {step === "finish" && (
                <button type="button" className="btn primary" onClick={closeApp}>
                  {t.done}
                </button>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
