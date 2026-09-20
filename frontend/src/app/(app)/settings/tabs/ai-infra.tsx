"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/lib/use-toast";
import SettingsCard from "@/components/settings/SettingsCard";
import SettingsField, {
  settingsButtonPrimary,
  settingsButtonSecondary,
  settingsInputStyle,
} from "@/components/settings/SettingsField";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

interface Credential {
  id: number;
  credential_type: string;
  label: string;
  priority: number;
  is_active: boolean;
  default_model: string;
  api_key_masked: string | null;
  project_id: string | null;
  location: string | null;
  client_email: string | null;
  private_key_id: string | null;
  private_key_configured: boolean;
  token_uri: string | null;
  is_exhausted_today: boolean;
  created_at: string;
}

type CredentialType = "gemini_api_key" | "vertex_service_account";

interface FormState {
  credential_type: CredentialType;
  label: string;
  api_key: string;
  project_id: string;
  location: string;
  client_email: string;
  private_key_id: string;
  private_key: string;
  token_uri: string;
  default_model: string;
  priority: number;
  is_active: boolean;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const GCP_REGIONS = [
  "us-central1",
  "us-east1",
  "us-east4",
  "us-west1",
  "us-west4",
  "europe-west1",
  "europe-west2",
  "europe-west3",
  "europe-west4",
  "europe-west6",
  "asia-south1",
  "asia-southeast1",
  "asia-east1",
  "asia-northeast1",
  "australia-southeast1",
  "northamerica-northeast1",
  "southamerica-east1",
];

const MODEL_SUGGESTIONS = [
  "gemini-2.5-flash-lite",
  "gemini-2.5-flash",
  "gemini-2.5-pro",
  "gemini-2.0-flash",
  "gemini-2.0-flash-lite",
];

const EMPTY_FORM: FormState = {
  credential_type: "gemini_api_key",
  label: "",
  api_key: "",
  project_id: "",
  location: "us-central1",
  client_email: "",
  private_key_id: "",
  private_key: "",
  token_uri: "https://oauth2.googleapis.com/token",
  default_model: "gemini-2.5-flash",
  priority: 1,
  is_active: true,
};

const BASE_URL = "/api/settings/ai-credentials";

/* ------------------------------------------------------------------ */
/*  Inline styles                                                     */
/* ------------------------------------------------------------------ */

const pillBase: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  padding: "2px 8px",
  borderRadius: 99,
  whiteSpace: "nowrap",
  display: "inline-block",
};

const rowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "10px 12px",
  borderRadius: 10,
  background: "var(--bg-secondary)",
  border: "1px solid var(--separator-light)",
};

const smallBtn: React.CSSProperties = {
  padding: "4px 8px",
  borderRadius: 6,
  border: "1px solid var(--separator)",
  background: "transparent",
  color: "var(--label-secondary)",
  fontSize: 12,
  fontWeight: 500,
  cursor: "pointer",
  lineHeight: 1,
};

const smallBtnDanger: React.CSSProperties = {
  ...smallBtn,
  color: "var(--act)",
  borderColor: "var(--act-edge, rgba(255,59,48,0.3))",
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function statusPillStyle(cred: Credential): React.CSSProperties {
  if (!cred.is_active) {
    return {
      ...pillBase,
      background: "var(--bg-secondary)",
      color: "var(--label-tertiary)",
      border: "1px solid var(--separator-light)",
    };
  }
  if (cred.is_exhausted_today) {
    return {
      ...pillBase,
      background: "var(--review-bg, rgba(255,149,0,0.08))",
      color: "var(--review)",
      border: "1px solid var(--review-edge, rgba(255,149,0,0.25))",
    };
  }
  return {
    ...pillBase,
    background: "var(--buy-bg, rgba(48,209,88,0.08))",
    color: "var(--buy)",
    border: "1px solid var(--buy-edge, rgba(48,209,88,0.25))",
  };
}

function statusLabel(cred: Credential): string {
  if (!cred.is_active) return "Inactive";
  if (cred.is_exhausted_today) return "Exhausted";
  return "Active";
}

function typeLabel(cred: Credential): string {
  return cred.credential_type === "vertex_service_account" ? "Vertex AI" : "API Key";
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export default function AiInfraSection() {
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const { toast } = useToast();

  const reload = useCallback(async () => {
    try {
      const list = await api.get<Credential[]>(`${BASE_URL}/`);
      setCredentials(list.sort((a, b) => a.priority - b.priority));
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  /* ---- Form helpers ---- */

  function openAdd() {
    setEditingId(null);
    setForm({ ...EMPTY_FORM, priority: credentials.length + 1 });
    setShowForm(true);
  }

  function openEdit(cred: Credential) {
    setEditingId(cred.id);
    setForm({
      credential_type: cred.credential_type as CredentialType,
      label: cred.label,
      api_key: "",
      project_id: cred.project_id ?? "",
      location: cred.location ?? "us-central1",
      client_email: cred.client_email ?? "",
      private_key_id: cred.private_key_id ?? "",
      private_key: "",
      token_uri: cred.token_uri ?? "https://oauth2.googleapis.com/token",
      default_model: cred.default_model,
      priority: cred.priority,
      is_active: cred.is_active,
    });
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
  }

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  /* ---- API actions ---- */

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        credential_type: form.credential_type,
        label: form.label,
        default_model: form.default_model,
        priority: form.priority,
        is_active: form.is_active,
      };

      if (form.credential_type === "gemini_api_key") {
        if (form.api_key) payload.api_key = form.api_key;
      } else {
        payload.project_id = form.project_id;
        payload.location = form.location;
        payload.client_email = form.client_email;
        payload.private_key_id = form.private_key_id;
        if (form.private_key) payload.private_key = form.private_key;
        payload.token_uri = form.token_uri;
      }

      if (editingId !== null) {
        await api.put(`${BASE_URL}/${editingId}`, payload);
        toast({ kind: "ok", text: "Credential updated" });
      } else {
        await api.post(`${BASE_URL}/`, payload);
        toast({ kind: "ok", text: "Credential added" });
      }
      closeForm();
      await reload();
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this credential? This cannot be undone.")) return;
    try {
      await api.delete(`${BASE_URL}/${id}`);
      toast({ kind: "ok", text: "Credential deleted" });
      await reload();
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Delete failed" });
    }
  }

  async function handleToggle(cred: Credential) {
    try {
      await api.put(`${BASE_URL}/${cred.id}`, { is_active: !cred.is_active });
      toast({ kind: "ok", text: cred.is_active ? "Credential disabled" : "Credential enabled" });
      await reload();
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Toggle failed" });
    }
  }

  async function handleReorder(cred: Credential, direction: "up" | "down") {
    const sorted = [...credentials].sort((a, b) => a.priority - b.priority);
    const idx = sorted.findIndex((c) => c.id === cred.id);
    const swapIdx = direction === "up" ? idx - 1 : idx + 1;
    if (swapIdx < 0 || swapIdx >= sorted.length) return;

    const other = sorted[swapIdx];
    try {
      await Promise.all([
        api.put(`${BASE_URL}/${cred.id}`, { priority: other.priority }),
        api.put(`${BASE_URL}/${other.id}`, { priority: cred.priority }),
      ]);
      await reload();
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Reorder failed" });
    }
  }

  /* ---- Credential count status ---- */

  const activeCount = credentials.filter((c) => c.is_active).length;
  const overallStatus = credentials.length === 0
    ? { kind: "warn" as const, label: "No credentials" }
    : activeCount === 0
      ? { kind: "warn" as const, label: "None active" }
      : { kind: "ok" as const, label: `${activeCount} active` };

  /* ---- Render ---- */

  const isVertexType = form.credential_type === "vertex_service_account";

  return (
    <SettingsCard
      title="Gemini AI Credentials"
      subtitle="Manage multiple Gemini API keys and Vertex AI service accounts. Credentials are tried in priority order; exhausted keys are automatically skipped."
      status={overallStatus}
      actions={
        !showForm ? (
          <button onClick={openAdd} style={settingsButtonPrimary}>
            Add credential
          </button>
        ) : null
      }
    >
      {/* ---- Credential list ---- */}
      {loading && (
        <div style={{ fontSize: 13, color: "var(--label-tertiary)", padding: "8px 0" }}>
          Loading...
        </div>
      )}

      {!loading && credentials.length === 0 && !showForm && (
        <div style={{ fontSize: 13, color: "var(--label-tertiary)", padding: "8px 0" }}>
          No credentials configured yet. Add one to get started.
        </div>
      )}

      {!loading && credentials.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {credentials.map((cred, idx) => (
            <div key={cred.id} style={rowStyle}>
              {/* Priority number */}
              <span
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: 6,
                  background: "var(--bg-primary)",
                  border: "1px solid var(--separator-light)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11,
                  fontWeight: 700,
                  color: "var(--label-tertiary)",
                  flexShrink: 0,
                }}
              >
                {cred.priority}
              </span>

              {/* Label + type + model */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "var(--label-primary)" }}>
                    {cred.label}
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      color: "var(--label-tertiary)",
                      background: "var(--bg-primary)",
                      border: "1px solid var(--separator-light)",
                      borderRadius: 4,
                      padding: "1px 6px",
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {typeLabel(cred)}
                  </span>
                  <span style={statusPillStyle(cred)}>
                    {statusLabel(cred)}
                  </span>
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--label-tertiary)",
                    fontFamily: "var(--font-mono)",
                    marginTop: 2,
                  }}
                >
                  {cred.default_model}
                  {cred.api_key_masked && <> &middot; {cred.api_key_masked}</>}
                  {cred.project_id && <> &middot; {cred.project_id}</>}
                </div>
              </div>

              {/* Actions */}
              <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
                <button
                  onClick={() => handleReorder(cred, "up")}
                  disabled={idx === 0}
                  style={{ ...smallBtn, opacity: idx === 0 ? 0.3 : 1 }}
                  title="Move up"
                >
                  &#9650;
                </button>
                <button
                  onClick={() => handleReorder(cred, "down")}
                  disabled={idx === credentials.length - 1}
                  style={{ ...smallBtn, opacity: idx === credentials.length - 1 ? 0.3 : 1 }}
                  title="Move down"
                >
                  &#9660;
                </button>
                <button onClick={() => openEdit(cred)} style={smallBtn} title="Edit">
                  Edit
                </button>
                <button
                  onClick={() => handleToggle(cred)}
                  style={smallBtn}
                  title={cred.is_active ? "Disable" : "Enable"}
                >
                  {cred.is_active ? "Disable" : "Enable"}
                </button>
                <button
                  onClick={() => handleDelete(cred.id)}
                  style={smallBtnDanger}
                  title="Delete"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ---- Add / Edit form ---- */}
      {showForm && (
        <form
          onSubmit={handleSubmit}
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 12,
            marginTop: 4,
            padding: "16px 18px",
            borderRadius: 12,
            border: "1px solid var(--separator-light)",
            background: "var(--bg-secondary)",
          }}
        >
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--label-primary)",
              fontFamily: "var(--font-serif)",
            }}
          >
            {editingId !== null ? "Edit credential" : "Add credential"}
          </div>

          {/* Type selector */}
          <SettingsField label="Type">
            <select
              value={form.credential_type}
              onChange={(e) => setField("credential_type", e.target.value as CredentialType)}
              style={{ ...settingsInputStyle, cursor: "pointer" }}
            >
              <option value="gemini_api_key">Gemini API Key</option>
              <option value="vertex_service_account">Vertex AI Service Account</option>
            </select>
          </SettingsField>

          {/* Label */}
          <SettingsField label="Label">
            <input
              type="text"
              value={form.label}
              onChange={(e) => setField("label", e.target.value)}
              placeholder="e.g. Primary key, Backup vertex SA"
              required
              style={settingsInputStyle}
            />
          </SettingsField>

          {/* API Key fields */}
          {!isVertexType && (
            <SettingsField label="API key" hint={editingId !== null ? "Leave blank to keep existing key" : undefined}>
              <input
                type="password"
                value={form.api_key}
                onChange={(e) => setField("api_key", e.target.value)}
                placeholder={editingId !== null ? "Enter new key to update" : "Enter Gemini API key"}
                required={editingId === null}
                style={settingsInputStyle}
              />
            </SettingsField>
          )}

          {/* Vertex SA fields */}
          {isVertexType && (
            <>
              <SettingsField label="Project ID">
                <input
                  type="text"
                  value={form.project_id}
                  onChange={(e) => setField("project_id", e.target.value)}
                  placeholder="my-gcp-project"
                  required
                  style={settingsInputStyle}
                />
              </SettingsField>

              <SettingsField label="Location">
                <select
                  value={form.location}
                  onChange={(e) => setField("location", e.target.value)}
                  required
                  style={{ ...settingsInputStyle, cursor: "pointer" }}
                >
                  {GCP_REGIONS.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </SettingsField>

              <SettingsField label="Client email">
                <input
                  type="email"
                  value={form.client_email}
                  onChange={(e) => setField("client_email", e.target.value)}
                  placeholder="sa-name@project.iam.gserviceaccount.com"
                  required
                  style={settingsInputStyle}
                />
              </SettingsField>

              <SettingsField label="Private key ID">
                <input
                  type="text"
                  value={form.private_key_id}
                  onChange={(e) => setField("private_key_id", e.target.value)}
                  placeholder="Key ID from service account JSON"
                  required
                  style={settingsInputStyle}
                />
              </SettingsField>

              <SettingsField
                label="Private key"
                hint={editingId !== null ? "Leave blank to keep existing key" : undefined}
              >
                <textarea
                  value={form.private_key}
                  onChange={(e) => setField("private_key", e.target.value)}
                  placeholder={editingId !== null ? "Paste new private key to update" : "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"}
                  required={editingId === null}
                  rows={4}
                  style={{ ...settingsInputStyle, resize: "vertical", fontFamily: "var(--font-mono)", fontSize: 12 }}
                />
              </SettingsField>

              <SettingsField label="Token URI">
                <input
                  type="url"
                  value={form.token_uri}
                  onChange={(e) => setField("token_uri", e.target.value)}
                  placeholder="https://oauth2.googleapis.com/token"
                  style={settingsInputStyle}
                />
              </SettingsField>
            </>
          )}

          {/* Default model */}
          <SettingsField label="Default model">
            <input
              type="text"
              list="gemini-model-suggestions"
              value={form.default_model}
              onChange={(e) => setField("default_model", e.target.value)}
              placeholder="gemini-2.5-flash"
              required
              style={settingsInputStyle}
            />
            <datalist id="gemini-model-suggestions">
              {MODEL_SUGGESTIONS.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </SettingsField>

          {/* Priority */}
          <SettingsField label="Priority" hint="Lower number = tried first">
            <input
              type="number"
              min={1}
              value={form.priority}
              onChange={(e) => setField("priority", Math.max(1, parseInt(e.target.value) || 1))}
              required
              style={{ ...settingsInputStyle, width: 80 }}
            />
          </SettingsField>

          {/* Buttons */}
          <div style={{ display: "flex", gap: 8, paddingTop: 4 }}>
            <button
              type="submit"
              disabled={saving}
              style={{ ...settingsButtonPrimary, opacity: saving ? 0.5 : 1 }}
            >
              {saving ? "Saving..." : editingId !== null ? "Update credential" : "Add credential"}
            </button>
            <button
              type="button"
              onClick={closeForm}
              style={settingsButtonSecondary}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </SettingsCard>
  );
}
