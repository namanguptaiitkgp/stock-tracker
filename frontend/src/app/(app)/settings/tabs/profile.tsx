"use client";

import { useEffect, useState } from "react";
import SettingsCard from "@/components/settings/SettingsCard";
import SettingsField, {
  settingsInputStyle,
  settingsButtonPrimary,
} from "@/components/settings/SettingsField";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/use-toast";
import { api } from "@/lib/api";

export default function ProfileTab() {
  const { user, setUser } = useAuth();
  const { toast } = useToast();

  // ── Profile details ──────────────────────────────────────────────
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);

  useEffect(() => {
    setUsername(user?.username ?? "");
    setEmail(user?.email ?? "");
  }, [user]);

  const profileDirty =
    username.trim() !== (user?.username ?? "") ||
    (email.trim() || "") !== (user?.email ?? "");

  async function saveProfile() {
    if (!profileDirty || savingProfile) return;
    setSavingProfile(true);
    try {
      const updated = await api.patch<{ id: number; username: string; email: string | null }>(
        "/api/user/profile",
        { username: username.trim(), email: email.trim() || null },
      );
      setUser({ id: updated.id, username: updated.username, email: updated.email });
      toast({ kind: "ok", text: "Profile updated" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Could not update profile" });
    } finally {
      setSavingProfile(false);
    }
  }

  // ── Change password ──────────────────────────────────────────────
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [savingPw, setSavingPw] = useState(false);

  const pwError =
    newPw && newPw.length < 6
      ? "New password must be at least 6 characters"
      : confirmPw && newPw !== confirmPw
        ? "Passwords do not match"
        : null;

  const canSubmitPw =
    !!currentPw && !!newPw && !!confirmPw && !pwError && !savingPw;

  async function changePassword() {
    if (!canSubmitPw) return;
    setSavingPw(true);
    try {
      await api.post("/api/user/change-password", {
        current_password: currentPw,
        new_password: newPw,
      });
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
      toast({ kind: "ok", text: "Password changed" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Could not change password" });
    } finally {
      setSavingPw(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SettingsCard
        title="Profile"
        subtitle="Your account name and contact email."
      >
        <SettingsField label="Username" htmlFor="pf-username">
          <input
            id="pf-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            style={settingsInputStyle}
          />
        </SettingsField>

        <SettingsField
          label="Email"
          htmlFor="pf-email"
          hint="Optional — used for account records only."
        >
          <input
            id="pf-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            placeholder="you@example.com"
            style={settingsInputStyle}
          />
        </SettingsField>

        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            onClick={saveProfile}
            disabled={!profileDirty || savingProfile}
            style={{
              ...settingsButtonPrimary,
              opacity: !profileDirty || savingProfile ? 0.5 : 1,
              cursor: !profileDirty || savingProfile ? "not-allowed" : "pointer",
            }}
          >
            {savingProfile ? "Saving…" : "Save changes"}
          </button>
        </div>
      </SettingsCard>

      <SettingsCard
        title="Change password"
        subtitle="You'll need your current password to set a new one."
      >
        <SettingsField label="Current password" htmlFor="pf-current-pw">
          <input
            id="pf-current-pw"
            type="password"
            value={currentPw}
            onChange={(e) => setCurrentPw(e.target.value)}
            autoComplete="current-password"
            style={settingsInputStyle}
          />
        </SettingsField>

        <SettingsField label="New password" htmlFor="pf-new-pw" hint="At least 6 characters.">
          <input
            id="pf-new-pw"
            type="password"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            autoComplete="new-password"
            style={settingsInputStyle}
          />
        </SettingsField>

        <SettingsField
          label="Confirm new password"
          htmlFor="pf-confirm-pw"
          error={pwError}
        >
          <input
            id="pf-confirm-pw"
            type="password"
            value={confirmPw}
            onChange={(e) => setConfirmPw(e.target.value)}
            autoComplete="new-password"
            style={settingsInputStyle}
          />
        </SettingsField>

        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            onClick={changePassword}
            disabled={!canSubmitPw}
            style={{
              ...settingsButtonPrimary,
              opacity: canSubmitPw ? 1 : 0.5,
              cursor: canSubmitPw ? "pointer" : "not-allowed",
            }}
          >
            {savingPw ? "Updating…" : "Update password"}
          </button>
        </div>
      </SettingsCard>
    </div>
  );
}
