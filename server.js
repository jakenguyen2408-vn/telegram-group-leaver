const express = require("express");
const cors = require("cors");
const { TelegramClient, Api } = require("telegram");
const { StringSession } = require("telegram/sessions");
const fs = require("fs");
const path = require("path");

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, "static")));

const SESSION_FILE = path.join(__dirname, "session.txt");
const CONFIG_FILE = path.join(__dirname, "config.json");

let client = null;
let phoneCodePromise = null; // { resolve }

function saveConfig(apiId, apiHash) {
  fs.writeFileSync(CONFIG_FILE, JSON.stringify({ apiId, apiHash }));
}

function loadConfig() {
  if (fs.existsSync(CONFIG_FILE)) {
    return JSON.parse(fs.readFileSync(CONFIG_FILE, "utf-8"));
  }
  return null;
}

function loadSession() {
  if (fs.existsSync(SESSION_FILE)) {
    return fs.readFileSync(SESSION_FILE, "utf-8").trim();
  }
  return "";
}

function saveSession() {
  if (client) {
    const s = client.session.save();
    fs.writeFileSync(SESSION_FILE, s);
  }
}

async function initClient(apiId, apiHash, sessionStr) {
  const session = new StringSession(sessionStr || "");
  client = new TelegramClient(session, parseInt(apiId), apiHash, {
    connectionRetries: 3,
  });
  await client.connect();
  return client;
}

// ── Auth Routes ────────────────────────────────

app.get("/auth/status", async (req, res) => {
  try {
    const config = loadConfig();
    if (!config) return res.json({ status: "need_config" });

    if (!client) {
      const sessionStr = loadSession();
      await initClient(config.apiId, config.apiHash, sessionStr);
    }

    const authorized = await client.checkAuthorization();
    if (authorized) {
      const me = await client.getMe();
      const name = [(me.firstName || ""), (me.lastName || "")].join(" ").trim();
      saveSession();
      return res.json({ status: "authorized", user: name, phone: me.phone });
    }
    return res.json({ status: "need_login" });
  } catch (e) {
    return res.json({ status: "need_config", error: e.message });
  }
});

// We need a special flow for GramJS: client.start() is interactive.
// Instead, we use sendCode + signIn manually.

let pendingPhone = null;
let pendingCodeHash = null;

app.post("/auth/send-code", async (req, res) => {
  const { api_id, api_hash, phone } = req.body;
  if (!api_id || !api_hash || !phone) {
    return res.status(400).json({ error: "api_id, api_hash, and phone are required" });
  }

  try {
    saveConfig(api_id, api_hash);
    await initClient(api_id, api_hash, "");

    const result = await client.invoke(
      new Api.auth.SendCode({
        phoneNumber: phone,
        apiId: parseInt(api_id),
        apiHash: api_hash,
        settings: new Api.CodeSettings({}),
      })
    );

    pendingPhone = phone;
    pendingCodeHash = result.phoneCodeHash;
    return res.json({ status: "code_sent" });
  } catch (e) {
    if (e.errorMessage && e.errorMessage.includes("FLOOD")) {
      return res.status(429).json({ error: `Rate limited. Wait ${e.seconds || 60} seconds.` });
    }
    return res.status(500).json({ error: e.message || String(e) });
  }
});

app.post("/auth/verify-code", async (req, res) => {
  const { phone, code, password } = req.body;

  if (!client) return res.status(400).json({ error: "Send code first" });

  try {
    const result = await client.invoke(
      new Api.auth.SignIn({
        phoneNumber: phone || pendingPhone,
        phoneCodeHash: pendingCodeHash,
        phoneCode: code,
      })
    );

    saveSession();
    const me = await client.getMe();
    const name = [(me.firstName || ""), (me.lastName || "")].join(" ").trim();
    return res.json({ status: "authorized", user: name });
  } catch (e) {
    if (e.errorMessage === "SESSION_PASSWORD_NEEDED") {
      if (password) {
        try {
          const srpResult = await client.invoke(new Api.account.GetPassword());
          const passwordSrp = await client.invoke(
            new Api.auth.CheckPassword({
              password: await client._computePasswordSrpCheck(srpResult, password),
            })
          );
          saveSession();
          const me = await client.getMe();
          const name = [(me.firstName || ""), (me.lastName || "")].join(" ").trim();
          return res.json({ status: "authorized", user: name });
        } catch (e2) {
          return res.status(401).json({ error: "2FA failed: " + (e2.message || String(e2)) });
        }
      }
      return res.json({ status: "need_2fa" });
    }
    if (e.errorMessage === "PHONE_CODE_INVALID") {
      return res.status(401).json({ error: "Invalid code. Please try again." });
    }
    return res.status(500).json({ error: e.message || String(e) });
  }
});

app.post("/logout", async (req, res) => {
  try {
    if (client) {
      await client.invoke(new Api.auth.LogOut());
    }
  } catch {}
  client = null;
  for (const f of [SESSION_FILE, CONFIG_FILE]) {
    if (fs.existsSync(f)) fs.unlinkSync(f);
  }
  return res.json({ status: "logged_out" });
});

// ── Group Routes ───────────────────────────

app.get("/groups", async (req, res) => {
  if (!client) return res.status(401).json({ error: "Not logged in" });

  try {
    const dialogs = await client.getDialogs({ limit: 500 });
    const groups = [];

    for (const d of dialogs) {
      const entity = d.entity;
      if (!entity) continue;

      const className = entity.className;

      if (className === "Chat") {
        groups.push({
          id: Number(entity.id),
          name: entity.title || "Untitled",
          type: "group",
          member_count: entity.participantsCount || 0,
          muted: !!(d.dialog?.notifySettings?.muteUntil),
          unread: d.unreadCount || 0,
        });
      } else if (className === "Channel") {
        groups.push({
          id: Number(entity.id),
          name: entity.title || "Untitled",
          type: entity.broadcast ? "channel" : "supergroup",
          member_count: entity.participantsCount || 0,
          muted: !!(d.dialog?.notifySettings?.muteUntil),
          unread: d.unreadCount || 0,
        });
      } else if (className === "ChatForbidden" || className === "ChannelForbidden") {
        groups.push({
          id: Number(entity.id),
          name: entity.title || "Forbidden",
          type: "forbidden",
          member_count: 0,
          muted: false,
          unread: 0,
        });
      }
    }

    return res.json({ groups });
  } catch (e) {
    return res.status(500).json({ error: e.message || String(e) });
  }
});

// ── Leave Route (SSE) ──────────────────────

app.post("/leave", async (req, res) => {
  if (!client) return res.status(401).json({ error: "Not logged in" });

  const { group_ids } = req.body;
  if (!group_ids || !group_ids.length) {
    return res.status(400).json({ error: "No groups selected" });
  }

  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");

  let success = 0;
  let failed = 0;
  const total = group_ids.length;

  // Build a map from dialogs to find entities
  let dialogMap = {};
  try {
    const dialogs = await client.getDialogs({ limit: 500 });
    for (const d of dialogs) {
      if (d.entity) {
        dialogMap[Number(d.entity.id)] = d;
      }
    }
  } catch {}

  for (let i = 0; i < group_ids.length; i++) {
    const gid = group_ids[i];
    const dialog = dialogMap[gid];

    try {
      if (dialog && dialog.entity) {
        const entity = dialog.entity;
        if (entity.className === "Channel") {
          await client.invoke(new Api.channels.LeaveChannel({ channel: entity }));
        } else if (entity.className === "Chat") {
          const me = await client.getMe();
          await client.invoke(
            new Api.messages.DeleteChatUser({
              chatId: entity.id,
              userId: me,
              revokeHistory: false
            })
          );
        } else {
          throw new Error("Cannot leave this type: " + entity.className);
        }
      } else {
        throw new Error("Group not found in dialogs");
      }

      success++;
      const data = JSON.stringify({
        group_id: gid, index: i + 1, total, status: "success"
      });
      res.write(`data: ${data}\n\n`);

    } catch (e) {
      const errMsg = e.errorMessage || e.message || String(e);

      if (errMsg.includes("FLOOD_WAIT") || errMsg.includes("FloodWait")) {
        const waitMatch = errMsg.match(/(\d+)/);
        const waitSecs = waitMatch ? parseInt(waitMatch[1]) : 30;

        const waitData = JSON.stringify({
          group_id: gid, index: i + 1, total,
          status: "flood_wait", wait_seconds: waitSecs
        });
        res.write(`data: ${waitData}\n\n`);

        // Wait it out
        await new Promise(r => setTimeout(r, (waitSecs + 1) * 1000));

        // Retry once
        try {
          const entity = dialog?.entity;
          if (entity?.className === "Channel") {
            await client.invoke(new Api.channels.LeaveChannel({ channel: entity }));
          } else if (entity?.className === "Chat") {
            const me = await client.getMe();
            await client.invoke(new Api.messages.DeleteChatUser({
              chatId: entity.id, userId: me, revokeHistory: false
            }));
          }
          success++;
          const retryData = JSON.stringify({
            group_id: gid, index: i + 1, total, status: "success"
          });
          res.write(`data: ${retryData}\n\n`);
        } catch (e2) {
          failed++;
          const failData = JSON.stringify({
            group_id: gid, index: i + 1, total,
            status: "failed", error: e2.message || String(e2)
          });
          res.write(`data: ${failData}\n\n`);
        }
      } else {
        failed++;
        const failData = JSON.stringify({
          group_id: gid, index: i + 1, total,
          status: "failed", error: errMsg
        });
        res.write(`data: ${failData}\n\n`);
      }
    }

    // Rate limit delay
    if (i < group_ids.length - 1) {
      await new Promise(r => setTimeout(r, 1500));
    }
  }

  // Summary
  const summary = JSON.stringify({ status: "complete", success, failed, total });
  res.write(`data: ${summary}\n\n`);
  res.end();
});

// ── Serve ──────────────────────────────────

app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "static", "index.html"));
});

const PORT = 5000;
app.listen(PORT, "127.0.0.1", () => {
  console.log("==================================================");
  console.log("  Telegram Group Leaver");
  console.log(`  Open http://localhost:${PORT} in your browser`);
  console.log("==================================================");
});
