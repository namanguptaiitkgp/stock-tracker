"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useTheme } from "@/lib/theme";
import { useToast } from "@/lib/use-toast";
import SettingsCard from "@/components/settings/SettingsCard";
import { settingsButtonPrimary, settingsInputStyle } from "@/components/settings/SettingsField";

interface Appearance {
  wallpaper_enabled: boolean;
  wallpaper_preset: string;
  wallpaper_url: string | null;
  wallpaper_upload: string | null;
  wallpaper_opacity: number;
}

const WALLPAPER_PRESETS = [
  { id: "none", name: "None", gradient: "linear-gradient(135deg, #0a0a0a, #050505)" },
  { id: "midnight", name: "Midnight", gradient: "linear-gradient(135deg, #0f172a, #1e293b, #0f172a)" },
  { id: "aurora", name: "Aurora", gradient: "linear-gradient(135deg, #1e1b4b, #312e81, #4c1d95)" },
  { id: "sunset", name: "Sunset", gradient: "linear-gradient(135deg, #0f172a, #1e3a8a, #4c1d95)" },
  { id: "forest", name: "Forest", gradient: "linear-gradient(135deg, #052e16, #064e3b, #052e16)" },
  { id: "ocean", name: "Ocean", gradient: "linear-gradient(135deg, #0f172a, #1e3a8a, #1e40af)" },
  { id: "graphite", name: "Graphite", gradient: "linear-gradient(135deg, #171717, #262626, #171717)" },
  { id: "mesh", name: "Mesh", gradient: "linear-gradient(135deg, #1e3a8a, #000000, #4c1d95)" },
];

export default function AppearanceTab() {
  const [appearance, setAppearance] = useState<Appearance | null>(null);
  const { theme, setTheme } = useTheme();
  const { toast } = useToast();

  useEffect(() => {
    api.get<Appearance>("/api/settings/appearance").then(setAppearance).catch(() => {});
  }, []);

  async function saveAppearance(updated: Partial<Appearance>) {
    if (!appearance) return;
    const next = { ...appearance, ...updated };
    setAppearance(next);
    try {
      await api.put("/api/settings/appearance", updated);
      toast({ kind: "ok", text: "Wallpaper updated — refresh page to apply" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Failed to save" });
    }
  }

  async function uploadWallpaper(file: File) {
    if (file.size > 8 * 1024 * 1024) {
      toast({ kind: "error", text: "Image too large (max 8 MB)" });
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/settings/wallpaper-upload`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${localStorage.getItem("algo_trader_token")}` },
          body: formData,
        },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Upload failed");
      }
      const updated = await api.get<Appearance>("/api/settings/appearance");
      setAppearance(updated);
      toast({ kind: "ok", text: "Wallpaper uploaded" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Upload failed" });
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SettingsCard
        title="Theme"
        subtitle="Light or dark interface. Saved per account."
      >
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => setTheme("light")}
            style={themeButtonStyle(theme === "light")}
          >
            Light
          </button>
          <button
            onClick={() => setTheme("dark")}
            style={themeButtonStyle(theme === "dark")}
          >
            Dark
          </button>
        </div>
      </SettingsCard>

      {appearance && (
        <SettingsCard
          title="Privacy Mode Wallpaper"
          subtitle="Covers your screen when Privacy Mode is on (Cmd/Ctrl+1 or the eye button). Not shown during normal use."
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <div style={labelStyle}>Choose wallpaper</div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: 8,
                }}
              >
                {appearance.wallpaper_upload && (
                  <PresetTile
                    label="My Image"
                    selected={!!appearance.wallpaper_url && appearance.wallpaper_url.startsWith("data:")}
                    backgroundImage={`url("${appearance.wallpaper_upload}")`}
                    onClick={() => saveAppearance({ wallpaper_url: appearance.wallpaper_upload!, wallpaper_preset: "none" })}
                  />
                )}
                {WALLPAPER_PRESETS.map((p) => (
                  <PresetTile
                    key={p.id}
                    label={p.name}
                    selected={appearance.wallpaper_preset === p.id && !appearance.wallpaper_url}
                    backgroundImage={p.gradient}
                    onClick={() => saveAppearance({ wallpaper_preset: p.id, wallpaper_url: "" })}
                  />
                ))}
              </div>
            </div>

            <div>
              <div style={labelStyle}>Custom wallpaper</div>
              {appearance.wallpaper_url && (
                <div style={{ marginBottom: 10 }}>
                  <div
                    style={{
                      width: "100%",
                      height: 128,
                      borderRadius: 10,
                      border: "1px solid var(--separator-light)",
                      backgroundImage: `url("${appearance.wallpaper_url}")`,
                      backgroundSize: "cover",
                      backgroundPosition: "center",
                    }}
                  />
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 6 }}>
                    <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
                      {appearance.wallpaper_url.startsWith("data:") ? "Uploaded image" : "External URL"}
                    </span>
                    <button
                      onClick={() => saveAppearance({ wallpaper_url: "" })}
                      style={{
                        background: "transparent", border: 0, padding: 0,
                        fontSize: 12, color: "var(--act)", cursor: "pointer", fontWeight: 500,
                      }}
                    >
                      Remove
                    </button>
                  </div>
                </div>
              )}

              <div style={{ display: "flex", gap: 8, alignItems: "stretch" }}>
                <label style={{ flex: "0 0 auto", cursor: "pointer" }}>
                  <span style={{ ...settingsButtonPrimary, display: "inline-block" }}>Upload image</span>
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/jpg,image/webp,image/gif"
                    style={{ display: "none" }}
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (file) await uploadWallpaper(file);
                      e.target.value = "";
                    }}
                  />
                </label>
                <input
                  type="url"
                  defaultValue={appearance.wallpaper_url && !appearance.wallpaper_url.startsWith("data:") ? appearance.wallpaper_url : ""}
                  placeholder="…or paste an image URL"
                  onBlur={(e) => {
                    const v = e.target.value.trim();
                    if (v && v !== (appearance.wallpaper_url || "")) {
                      saveAppearance({ wallpaper_url: v, wallpaper_preset: "none" });
                    }
                  }}
                  style={{ ...settingsInputStyle, flex: 1 }}
                />
              </div>
              <div style={{ fontSize: 11, color: "var(--label-quaternary)", marginTop: 6 }}>
                PNG, JPEG, WebP, GIF up to 8 MB. URLs work too.
              </div>
            </div>

            <div>
              <div style={{ ...labelStyle, display: "flex", justifyContent: "space-between" }}>
                <span>Opacity</span>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--label-secondary)" }}>
                  {Math.round(appearance.wallpaper_opacity * 100)}%
                </span>
              </div>
              <input
                type="range"
                min={0.1}
                max={1}
                step={0.05}
                value={appearance.wallpaper_opacity}
                onChange={(e) => setAppearance({ ...appearance, wallpaper_opacity: Number(e.target.value) })}
                onMouseUp={(e) => saveAppearance({ wallpaper_opacity: Number((e.target as HTMLInputElement).value) })}
                onTouchEnd={(e) => saveAppearance({ wallpaper_opacity: Number((e.target as HTMLInputElement).value) })}
                style={{ width: "100%", accentColor: "var(--system-blue)" }}
              />
            </div>

            <div
              style={{
                fontSize: 12,
                color: "var(--label-tertiary)",
                padding: "8px 10px",
                borderRadius: 8,
                background: "var(--bg-secondary)",
                border: "1px solid var(--separator-light)",
              }}
            >
              Tip: press <kbd style={kbdStyle}>Cmd</kbd>/<kbd style={kbdStyle}>Ctrl</kbd> + <kbd style={kbdStyle}>1</kbd> to toggle Privacy Mode anywhere in the app.
            </div>
          </div>
        </SettingsCard>
      )}
    </div>
  );
}

function PresetTile({ label, selected, backgroundImage, onClick }: {
  label: string;
  selected: boolean;
  backgroundImage: string;
  onClick: () => void;
}) {
  const isImage = backgroundImage.startsWith("url(");
  return (
    <button
      onClick={onClick}
      style={{
        position: "relative",
        height: 64,
        borderRadius: 10,
        border: selected ? "2px solid var(--system-blue)" : "1px solid var(--separator-light)",
        boxShadow: selected ? "0 0 0 3px color-mix(in srgb, var(--system-blue) 22%, transparent)" : "none",
        background: isImage ? undefined : backgroundImage,
        backgroundImage: isImage ? backgroundImage : undefined,
        backgroundSize: "cover",
        backgroundPosition: "center",
        cursor: "pointer",
        padding: 0,
        overflow: "hidden",
        transition: "box-shadow .15s, border-color .15s",
      }}
    >
      <span
        style={{
          position: "absolute",
          left: 8,
          bottom: 6,
          fontSize: 11,
          fontWeight: 500,
          color: "rgba(255,255,255,0.92)",
          textShadow: "0 1px 2px rgba(0,0,0,0.45)",
        }}
      >
        {label}
      </span>
    </button>
  );
}

function themeButtonStyle(active: boolean): React.CSSProperties {
  return {
    padding: "8px 18px",
    borderRadius: 8,
    border: active ? "1px solid var(--label-primary)" : "1px solid var(--separator)",
    background: active ? "var(--label-primary)" : "transparent",
    color: active ? "var(--bg-primary)" : "var(--label-secondary)",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
  };
}

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  color: "var(--label-tertiary)",
  marginBottom: 8,
};

const kbdStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "1px 6px",
  borderRadius: 4,
  background: "var(--bg-primary)",
  border: "1px solid var(--separator)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
};
