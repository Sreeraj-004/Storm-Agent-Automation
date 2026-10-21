
import { useState, useEffect } from "react";
import {
  Activity,
  Bot,
  CalendarDays,
  CheckCheck,
  MessageCircle,
  MoreHorizontal,
  Paperclip,
  Phone,
  Plus,
  Search,
  Send,
  Settings,
  Smile,
  Users,
  Video,
} from "lucide-react";
import "./App.css";
const API_BASE_URL = "http://127.0.0.1:8000";



const USERS = {
  user1: { id: "user1", name: "Storm approver", initials: "SA" },
  user2: { id: "user2", name: "Change Manager", initials: "CM" },
};

const initialPersonalChats = {
  user1: [
    {
      id: "alex",
      name: "Alex Johnson",
      initials: "AJ",
      color: "#dcdafa",
      status: "Available",
      preview: "Can you review the latest update?",
      time: "9:42 AM",
      messages: [
        {
          id: 1,
          sender: "Alex Johnson",
          text: "Can you review the latest update?",
          time: "9:42 AM",
        },
      ],
    },
    {
      id: "ops-team",
      name: "Operations Team",
      initials: "OT",
      color: "#d5eddf",
      status: "Team chat",
      preview: "Daily operations review at 10:30 AM",
      time: "9:30 AM",
      messages: [
        {
          id: 2,
          sender: "Operations Team",
          text: "Daily operations review at 10:30 AM.",
          time: "9:30 AM",
        },
      ],
    },
  ],
  user2: [
    {
      id: "sarah",
      name: "Sarah Miller",
      initials: "SM",
      color: "#f4d9e7",
      status: "Available",
      preview: "The change request is ready.",
      time: "9:15 AM",
      messages: [
        {
          id: 3,
          sender: "Sarah Miller",
          text: "The change request is ready for review.",
          time: "9:15 AM",
        },
      ],
    },
    {
      id: "change-team",
      name: "Change Advisory Team",
      initials: "CA",
      color: "#d5e8fa",
      status: "Team chat",
      preview: "Please check pending changes.",
      time: "8:55 AM",
      messages: [
        {
          id: 4,
          sender: "Change Advisory Team",
          text: "Please check the pending change requests.",
          time: "8:55 AM",
        },
      ],
    },
  ],
};

const initialStormMessages = [
  {
    id: 100,
    sender: "Storm Bot",
    senderId: "bot",
    text: "Storm Bot is online. I will post weather alerts and change-freeze notifications here.",
    time: "9:00 AM",
    system: true,
  },
];

function getTime() {
  return new Date().toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}


function toDateTimeLocal(value) {
  if (!value) return "";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "";

  const offset = date.getTimezoneOffset() * 60_000;

  return new Date(date.getTime() - offset)
    .toISOString()
    .slice(0, 16);
}


function toStormDraft(alert) {
  return {
    location: alert.location ?? "Merrillville, Indiana",
    event: alert.event ?? "",
    severity: alert.severity ?? "Severe",
    description: alert.description ?? alert.headline ?? "",
    suggested_start: toDateTimeLocal(alert.suggested_start),
    suggested_end: toDateTimeLocal(alert.suggested_end),
  };
}


function App() {
  
  const [changeExceptions, setChangeExceptions] = useState([]);
  const [exceptionError, setExceptionError] = useState("");
  const [submittingExceptionId, setSubmittingExceptionId] = useState(null);
  const [stormRequests, setStormRequests] = useState([]);
  const [stormDrafts, setStormDrafts] = useState({});
  const [stormApiError, setStormApiError] = useState("");
  const [submittingStormId, setSubmittingStormId] = useState(null);
  const [closingStormId, setClosingStormId] = useState(null);
  const [currentUserId, setCurrentUserId] = useState("user1");
  const [personalChats, setPersonalChats] = useState(initialPersonalChats);
  const [stormMessages, setStormMessages] = useState(initialStormMessages);
  const [activeChatId, setActiveChatId] = useState("storm-bot");
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [activeNavigation, setActiveNavigation] = useState("Chat");
  const [mobileConversationOpen, setMobileConversationOpen] =
    useState(false);

  const currentUser = USERS[currentUserId];

  const stormChat = {
    id: "storm-bot",
    name: "Storm Bot",
    initials: "SB",
    color: "#fbe6c8",
    status: "Weather alert assistant",
    preview: stormMessages[stormMessages.length - 1]?.text ?? "No messages yet",
    time: stormMessages[stormMessages.length - 1]?.time ?? "",
    isBot: true,
    messages: stormMessages,
  };

  const currentPersonalChats = personalChats[currentUserId];
  const allChats = [stormChat, ...currentPersonalChats];

  const filteredChats = allChats.filter((chat) =>
    chat.name.toLowerCase().includes(search.toLowerCase())
  );

  const activeChat = allChats.find((chat) => chat.id === activeChatId);
  
useEffect(() => {
  let active = true;

  async function loadStormRequests() {
    try {
      const response = await fetch(
        `${API_BASE_URL}/storm-mode/requests`
      );

      if (!response.ok) {
        throw new Error("Unable to load Storm Mode requests.");
      }

      const data = await response.json();

      if (!active) return;

      setStormRequests(data.requests);

      setStormDrafts((current) => {
        const next = { ...current };

        for (const alert of data.requests) {
          if (!next[alert.id] || alert.status !== "pending") {
            next[alert.id] = toStormDraft(alert);
          }
        }

        return next;
      });

      setStormApiError("");
    } catch (error) {
      if (active) {
        setStormApiError(error.message);
      }
    }
  }

  loadStormRequests();
  const intervalId = window.setInterval(loadStormRequests, 5000);

  return () => {
    active = false;
    window.clearInterval(intervalId);
  };
}, []);


useEffect(() => {
  if (currentUserId !== "user2") return;

  let active = true;

  async function loadChangeExceptions() {
    try {
      const response = await fetch(
        `${API_BASE_URL}/storm-mode/exceptions?status=pending`
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Unable to load change exceptions."
        );
      }

      if (active) {
        setChangeExceptions(data.exceptions ?? []);
        setExceptionError("");
      }
    } catch (error) {
      if (active) {
        setExceptionError(error.message);
      }
    }
  }

  loadChangeExceptions();

  const intervalId = window.setInterval(
    loadChangeExceptions,
    5000
  );

  return () => {
    active = false;
    window.clearInterval(intervalId);
  };
}, [currentUserId]);


async function simulateStormAlert() {
  try {
    setStormApiError("");

    const response = await fetch(
      `${API_BASE_URL}/weather/merrillville/alerts/simulate`,
      { method: "POST" }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Unable to simulate storm alert.");
    }

    setStormRequests((current) => [
      data.alert,
      ...current.filter((item) => item.id !== data.alert.id),
    ]);

    setStormDrafts((current) => ({
      ...current,
      [data.alert.id]: toStormDraft(data.alert),
    }));

    setActiveChatId("storm-bot");
    setActiveNavigation("Chat");
    setMobileConversationOpen(true);
  } catch (error) {
    setStormApiError(error.message);
  }
}

function updateStormDraft(alertId, field, value) {
  setStormDrafts((current) => ({
    ...current,
    [alertId]: {
      ...current[alertId],
      [field]: value,
    },
  }));
}

async function decideStormMode(alertId, decision) {
  const draft = stormDrafts[alertId];

  if (!draft) return;

  if (
    !draft.location.trim() ||
    !draft.event.trim() ||
    !draft.description.trim() ||
    !draft.suggested_start ||
    !draft.suggested_end
  ) {
    setStormApiError("Complete all storm details before deciding.");
    return;
  }

  if (
    new Date(draft.suggested_end) <=
    new Date(draft.suggested_start)
  ) {
    setStormApiError("The end time must be after the start time.");
    return;
  }

  setSubmittingStormId(alertId);
  setStormApiError("");

  try {
    const response = await fetch(
      `${API_BASE_URL}/storm-mode/requests/${alertId}/decision`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...draft,
          suggested_start: new Date(draft.suggested_start).toISOString(),
          suggested_end: new Date(draft.suggested_end).toISOString(),
          decision,
        }),
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Unable to submit the decision.");
    }
    
    if (decision === "approve" && data.freeze_result) {
      const result = data.freeze_result;

      const sections = [
        ["HIGH RISK", result.high_risk_changes ?? []],
        ["LOW RISK", result.low_risk_changes ?? []],
        ["REVIEW REQUIRED", result.review_required ?? []],
      ];

      const lines = [
        "Storm freeze processing completed.",
        `Total changes: ${result.total_changes ?? 0}`,
        `High risk: ${result.high_risk_count ?? 0}`,
        `Low risk: ${result.low_risk_count ?? 0}`,
        `Review required: ${result.review_required_count ?? 0}`,
        "",
      ];

      for (const [heading, changes] of sections) {
        if (changes.length === 0) continue;

        lines.push(`--- ${heading} ---`);

        for (const change of changes) {
          const assessment = change.risk_assessment ?? {};

          lines.push(
            `${change.number ?? "Unknown change"}: ${
              change.short_description ?? "No description"
            }`,
            `Summary: ${
              assessment.flag_summary ?? "No summary available"
            }`,
            `Impact if delayed: ${
              assessment.business_impact_if_delayed ?? "Unknown"
            }`,
            `Reason: ${assessment.reason ?? "Not provided"}`,
            ""
          );
        }
      }

      if (result.status === "partial_failure") {
        lines.push(
          "WARNING: Some work-note updates need verification."
        );
      }

      setStormMessages((current) => [
        ...current,
        {
          id: `risk-analysis-${alertId}`,
          sender: "Storm Bot",
          senderId: "bot",
          text: lines.join("\n"),
          time: getTime(),
          system: true,
        },
      ]);
    }


    setStormRequests((current) =>
      current.map((alert) =>
        alert.id === alertId ? data.alert : alert
      )
    );

    setStormDrafts((current) => ({
      ...current,
      [alertId]: toStormDraft(data.alert),
    }));
  } catch (error) {
    setStormApiError(error.message);
  } finally {
    setSubmittingStormId(null);
  }
}


async function closeStormMode(alertId) {
  const confirmed = window.confirm(
    "Close Storm Mode and notify scheduled changes that the freeze is lifted?"
  );

  if (!confirmed) return;

  setClosingStormId(alertId);
  setStormApiError("");

  try {
    const response = await fetch(
      `${API_BASE_URL}/storm-mode/requests/${alertId}/close`,
      { method: "POST" }
    );

    const data = await response.json();

    if (!response.ok) {
      const detail = data.detail;
      const errorMessage =
        typeof detail === "string"
          ? detail
          : detail?.message || "Unable to close Storm Mode.";

      throw new Error(errorMessage);
    }

    setStormRequests((current) =>
      current.map((alert) =>
        alert.id === alertId
          ? { ...alert, ...data, status: "closed" }
          : alert
      )
    );

    setStormMessages((current) => [
      ...current,
      {
        id: `storm-closed-${alertId}`,
        sender: "Storm Bot",
        senderId: "bot",
        text:
          `Storm Mode has been closed for alert ${alertId}. ` +
          "The backend confirmed that work notes were added to all matching scheduled changes.",
        time: getTime(),
        system: true,
      },
    ]);
  } catch (error) {
    setStormApiError(error.message);
  } finally {
    setClosingStormId(null);
  }
}

  
async function decideException(change, decision) {
  const key = `${change.alert_id}-${change.sys_id}`;

  setSubmittingExceptionId(key);
  setExceptionError("");

  try {
    const response = await fetch(
      `${API_BASE_URL}/storm-mode/exceptions/${change.alert_id}/${change.sys_id}/decision`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ decision }),
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "ServiceNow decision update failed."
      );
    }

    if (data.work_note_status !== "updated") {
      throw new Error(
        "The decision work note was not confirmed."
      );
    }

    // Update the UI only after the backend confirms success.
    setChangeExceptions((current) =>
      current.map((item) =>
        item.alert_id === change.alert_id &&
        item.sys_id === change.sys_id
          ? {
              ...item,
              exception_status: data.exception_status,
              decision_note_status: data.work_note_status,
            }
          : item
      )
    );
  } catch (error) {
    setExceptionError(error.message);
  } finally {
    setSubmittingExceptionId(null);
  }
}


  function switchUser(event) {
    const nextUserId = event.target.value;

    setCurrentUserId(nextUserId);
    setActiveChatId("storm-bot");
    setActiveNavigation("Chat");
    setMobileConversationOpen(false);
    setSearch("");
    setMessage("");
  }

  function selectChat(chatId) {
    setActiveChatId(chatId);
    setMobileConversationOpen(true);
  }

  function sendMessage(event) {
    event.preventDefault();

    const text = message.trim();

    if (!text || !activeChat) {
      return;
    }

    const newMessage = {
      id: `${currentUserId}-${Date.now()}`,
      sender: currentUser.name,
      senderId: currentUserId,
      text,
      time: getTime(),
    };

    if (activeChatId === "storm-bot") {
      setStormMessages((currentMessages) => [
        ...currentMessages,
        newMessage,
      ]);
    } else {
      setPersonalChats((currentChats) => ({
        ...currentChats,
        [currentUserId]: currentChats[currentUserId].map((chat) =>
          chat.id === activeChatId
            ? {
                ...chat,
                preview: text,
                time: newMessage.time,
                messages: [...chat.messages, newMessage],
              }
            : chat
        ),
      }));
    }

    setMessage("");
  }

  function createChat() {
    const name = window.prompt("Enter a name for the new chat:");

    if (!name?.trim()) {
      return;
    }

    const normalizedName = name.trim();

    const existingChat = currentPersonalChats.find(
      (chat) => chat.name.toLowerCase() === normalizedName.toLowerCase()
    );

    if (existingChat) {
      selectChat(existingChat.id);
      return;
    }

    const newChat = {
      id: `${currentUserId}-${Date.now()}`,
      name: normalizedName,
      initials: normalizedName
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part[0].toUpperCase())
        .join(""),
      color: "#dcdafa",
      status: "Private conversation",
      preview: "Start a conversation",
      time: "Now",
      messages: [],
    };

    setPersonalChats((currentChats) => ({
      ...currentChats,
      [currentUserId]: [newChat, ...currentChats[currentUserId]],
    }));

    setActiveChatId(newChat.id);
    setSearch("");
    setMobileConversationOpen(true);
  }

  return (
    <main className="teams-app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">T</div>
          <span>Teams</span>
        </div>

        <label className="top-search">
          <Search size={17} />
          <input
            type="search"
            placeholder="Search workspace"
            aria-label="Search workspace"
          />
        </label>

        <div className="topbar-actions">
          <label className="user-switcher">
            <Users size={16} />
            <select
              value={currentUserId}
              onChange={switchUser}
              aria-label="Switch user"
            >
              <option value="user1">Operations User</option>
              <option value="user2">Change Manager</option>
            </select>
          </label>

          <button
            className="icon-button top-icon"
            type="button"
            aria-label="Settings"
          >
            <Settings size={20} />
          </button>

          <div className="profile-avatar" title={currentUser.name}>
            {currentUser.initials}
          </div>
        </div>
      </header>

      <div
        className={`workspace ${
          mobileConversationOpen ? "mobile-chat-open" : ""
        }`}
      >
        <nav className="rail" aria-label="Main navigation">
          {[
            { name: "Activity", Icon: Activity },
            { name: "Chat", Icon: MessageCircle },
            { name: "Teams", Icon: Users },
            { name: "Calendar", Icon: CalendarDays },
            { name: "Calls", Icon: Phone },
          ].map(({ name, Icon }) => (
            <button
              key={name}
              className={`rail-item ${
                activeNavigation === name ? "active" : ""
              }`}
              onClick={() => {
                setActiveNavigation(name);
                setMobileConversationOpen(false);
              }}
              type="button"
            >
              <Icon />
              <span>{name}</span>
            </button>
          ))}
        </nav>

        <aside className="chat-sidebar">
          <div className="sidebar-heading">
            <div>
              <h1>{activeNavigation}</h1>
              <p className="user-context">
                Signed in as {currentUser.name}
              </p>
            </div>

            <button
              className="icon-button"
              onClick={createChat}
              aria-label="Create new chat"
              title="New chat"
              type="button"
            >
              <Plus size={21} />
            </button>
          </div>

          <div className="chat-tabs">
            <button className="tab active-tab" type="button">
              All
            </button>
            <button
              className="tab"
              onClick={() => setSearch("")}
              type="button"
            >
              Recent
            </button>
          </div>

          <label className="chat-search">
            <Search size={16} />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search chats"
              aria-label="Search chats"
            />
          </label>

          <div className="chat-list">
            <div className="section-label">SHARED</div>

            <button
              className={`chat-item ${
                activeChatId === "storm-bot" ? "selected-chat" : ""
              }`}
              onClick={() => selectChat("storm-bot")}
              type="button"
            >
              <div className="avatar bot-avatar">
                <Bot size={21} />
              </div>

              <div className="chat-summary">
                <div className="chat-name">Storm Bot</div>
                <div className="chat-preview">{stormChat.preview}</div>
              </div>

              <span className="chat-time">{stormChat.time}</span>
            </button>

            <div className="section-label private-label">
              YOUR CHATS
            </div>

            {filteredChats
              .filter((chat) => !chat.isBot)
              .map((chat) => (
                <button
                  key={chat.id}
                  className={`chat-item ${
                    chat.id === activeChatId ? "selected-chat" : ""
                  }`}
                  onClick={() => selectChat(chat.id)}
                  type="button"
                >
                  <div
                    className="avatar"
                    style={{ backgroundColor: chat.color }}
                  >
                    {chat.initials}
                  </div>

                  <div className="chat-summary">
                    <div className="chat-name">{chat.name}</div>
                    <div className="chat-preview">{chat.preview}</div>
                  </div>

                  <span className="chat-time">{chat.time}</span>
                </button>
              ))}

            {filteredChats.filter((chat) => !chat.isBot).length === 0 && (
              <p className="empty-search">No matching private chats found.</p>
            )}
          </div>
        </aside>

        {activeNavigation === "Chat" ? (
          <section className="conversation">
            {activeChat ? (
              <>
                <header className="conversation-header">
                  <button
                    className="icon-button mobile-back"
                    onClick={() => setMobileConversationOpen(false)}
                    aria-label="Back to chats"
                    type="button"
                  >
                    <span aria-hidden="true">←</span>
                  </button>

                  <div
                    className={`avatar ${
                      activeChat.isBot ? "bot-avatar" : ""
                    }`}
                    style={
                      activeChat.isBot
                        ? undefined
                        : { backgroundColor: activeChat.color }
                    }
                  >
                    {activeChat.isBot ? (
                      <Bot size={21} />
                    ) : (
                      activeChat.initials
                    )}
                  </div>

                  <div className="conversation-identity">
                    <h2>{activeChat.name}</h2>
                    <span className="presence">
                      {activeChat.isBot
                        ? "Shared conversation · Visible to both users"
                        : activeChat.status}
                    </span>
                  </div>

                  <div className="conversation-actions">
                    
                    {activeChat.isBot && (
                      <button
                        className="simulate-button"
                        type="button"
                        onClick={simulateStormAlert}
                      >
                        + Simulate storm
                      </button>
                    )}

                    <button
                      className="icon-button"
                      aria-label="Audio call"
                      type="button"
                    >
                      <Phone size={19} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label="Video call"
                      type="button"
                    >
                      <Video size={20} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label="More options"
                      type="button"
                    >
                      <MoreHorizontal size={21} />
                    </button>
                  </div>
                </header>

                <div className="message-area">
                  <div className="conversation-intro">
                    <div
                      className={`large-avatar ${
                        activeChat.isBot ? "bot-avatar" : ""
                      }`}
                      style={
                        activeChat.isBot
                          ? undefined
                          : { backgroundColor: activeChat.color }
                      }
                    >
                      {activeChat.isBot ? (
                        <Bot size={30} />
                      ) : (
                        activeChat.initials
                      )}
                    </div>

                    <h2>{activeChat.name}</h2>
                    <p>
                      {activeChat.isBot
                        ? "Shared storm alerts and change notifications for Operations and Change Management."
                        : `Private conversation with ${activeChat.name}.`}
                    </p>
                  </div>

                  
                {activeChat.messages.map((item) => (
                  <div
                    key={item.id}
                    className={`message-row ${
                      item.senderId === currentUserId ? "own-message" : ""
                    } ${item.system ? "system-message" : ""}`}
                  >
                    <div className="message-content">
                      <div className="message-meta">
                        <strong>{item.sender}</strong>
                        <span>{item.time}</span>
                      </div>

                      <div className="message-bubble">{item.text}</div>

                      {item.senderId === currentUserId && (
                        <CheckCheck
                          className="read-indicator"
                          size={15}
                          aria-label="Sent"
                        />
                      )}
                    </div>
                  </div>
                ))}

                {activeChat.isBot && currentUserId === "user2" && (
                  <div className="exception-approval-center">
                    <h2>Change Exception Approval Center</h2>
                    <p>
                      Review high-risk changes and decide whether they may
                      proceed during the storm freeze.
                    </p>

                    {exceptionError && (
                      <p className="storm-api-error" role="alert">
                        {exceptionError}
                      </p>
                    )}

                    {changeExceptions.map((change) => (
                      <article
                        className="storm-card"
                        key={`${change.alert_id}-${change.sys_id}`}
                      >
                        <h3>
                          {change.number} {change.short_description}
                        </h3>

                        <p>
                          <strong>AI assessment:</strong>{" "}
                          {change.risk_assessment?.risk_classification}
                        </p>

                        <p>
                          <strong>Why flagged:</strong>{" "}
                          {change.risk_assessment?.flag_summary}
                        </p>

                        <p>
                          <strong>Impact if postponed:</strong>{" "}
                          {change.risk_assessment?.business_impact_if_delayed}
                        </p>

                        <p>{change.risk_assessment?.reason}</p>

                        <p>
                          Status: {change.exception_status}
                        </p>

                        {change.exception_status === "pending" && (
                          <div className="storm-card-actions">
                            <button
                              className="approve-button"
                              disabled={
                                submittingExceptionId ===
                                  `${change.alert_id}-${change.sys_id}`
                              }
                              onClick={() => decideException(change, "approve")}
                            >
                              Approve to Proceed
                            </button>

                            <button
                              className="reject-button"
                              disabled={
                                submittingExceptionId ===
                                  `${change.alert_id}-${change.sys_id}`
                              }
                              onClick={() => decideException(change, "reject")}
                            >
                              Reject Exception
                            </button>
                            <p>
                          Request will be auto rejected in 24 hours
                        </p>
                          </div>
                          
                        )}
                      </article>
                    ))}

                    {changeExceptions.length === 0 && (
                      <p>No change exceptions require review.</p>
                    )}
                  </div>
                )}

                {activeChat.isBot && currentUserId === "user1" && (
                  <div className="storm-request-list">
                    {stormApiError && (
                      <p className="storm-api-error" role="alert">
                        {stormApiError}
                      </p>
                    )}

                    {(currentUserId === "user1" ? stormRequests : []).map((alert) => {
                      const draft = stormDrafts[alert.id] ?? toStormDraft(alert);
                      const pending = String(alert.status ?? "").toLowerCase() === "pending";
                      const submitting = submittingStormId === alert.id;

                      return (
                        <article className="storm-card" key={alert.id}>
                          <div className="storm-card-heading">
                            <span className="storm-icon">⚡</span>

                            <div>
                              <h3>Storm Mode Activation Request</h3>
                              <p>Review the storm details and activation window</p>
                            </div>

                            <span className={`storm-status ${alert.status}`}>
                              {alert.status}
                            </span>
                          </div>

                          <form
                            className="storm-card-body"
                            onSubmit={(event) => {
                              event.preventDefault();
                              decideStormMode(alert.id, "approve");
                            }}
                          >
                            <label className="storm-field">
                              Location
                              <input
                                value={draft.location}
                                disabled={submitting}
                                onChange={(event) =>
                                  updateStormDraft(
                                    alert.id,
                                    "location",
                                    event.target.value
                                  )
                                }
                                required
                              />
                            </label>

                            <label className="storm-field">
                              Storm event
                              <input
                                value={draft.event}
                                disabled={!pending || submitting}
                                onChange={(event) =>
                                  updateStormDraft(
                                    alert.id,
                                    "event",
                                    event.target.value
                                  )
                                }
                                required
                              />
                            </label>

                            <label className="storm-field">
                              Severity
                              <select
                                value={draft.severity}
                                disabled={!pending || submitting}
                                onChange={(event) =>
                                  updateStormDraft(
                                    alert.id,
                                    "severity",
                                    event.target.value
                                  )
                                }
                              >
                                <option value="Minor">Minor</option>
                                <option value="Moderate">Moderate</option>
                                <option value="Severe">Severe</option>
                                <option value="Extreme">Extreme</option>
                              </select>
                            </label>

                            <label className="storm-field">
                              Storm details
                              <textarea
                                rows={3}
                                value={draft.description}
                                disabled={!pending || submitting}
                                onChange={(event) =>
                                  updateStormDraft(
                                    alert.id,
                                    "description",
                                    event.target.value
                                  )
                                }
                                required
                              />
                            </label>

                            
                            <div className="storm-details">
                              <label className="storm-field">
                                Suggested start date & time
                                <input
                                  type="datetime-local"
                                  value={draft.suggested_start || ""}
                                  disabled={submitting}
                                  onClick={(event) => event.currentTarget.showPicker()}
                                  onChange={(event) =>
                                    updateStormDraft(
                                      alert.id,
                                      "suggested_start",
                                      event.target.value
                                    )
                                  }
                                  required
                                />
                              </label>

                              <label className="storm-field">
                                Suggested end date & time
                                <input
                                  type="datetime-local"
                                  value={draft.suggested_end || ""}
                                  min={draft.suggested_start || undefined}
                                  disabled={submitting}
                                  onClick={(event) => event.currentTarget.showPicker()}
                                  onChange={(event) =>
                                    updateStormDraft(
                                      alert.id,
                                      "suggested_end",
                                      event.target.value
                                    )
                                  }
                                  required
                                />
                              </label>
                            </div>


                            {pending ? (
                              <div className="storm-card-actions">
                                <button
                                  className="approve-button"
                                  type="submit"
                                  disabled={submitting}
                                >
                                  {submitting ? "Submitting..." : "Approve"}
                                </button>

                                <button
                                  className="reject-button"
                                  type="button"
                                  disabled={submitting}
                                  onClick={() =>
                                    decideStormMode(alert.id, "reject")
                                  }
                                >
                                  Reject
                                </button>
                              </div>
                           
                                ) : (
                                  <>
                                    <p className="decision-message">
                                      Storm Mode {alert.status}.
                                      {alert.decision_at &&
                                        ` Decided at ${new Date(
                                          alert.decision_at
                                        ).toLocaleString()}`}
                                    </p>

                                    {alert.status === "approved" && (
                                      <div className="storm-card-actions">
                                        <button
                                          className="reject-button"
                                          type="button"
                                          disabled={closingStormId === alert.id}
                                          onClick={() => closeStormMode(alert.id)}
                                        >
                                          {closingStormId === alert.id
                                            ? "Closing Storm Mode..."
                                            : "Close Storm Mode"}
                                        </button>
                                      </div>
                                    )}

                                    {alert.status === "closed" && (
                                      <p className="decision-message">
                                        Storm Mode closed. Scheduled changes have been notified.
                                      </p>
                                    )}
                                  </>
                                )}

                          </form>

                          <p className="demo-disclaimer">
                            DEMO ALERT — Not an official weather warning.
                          </p>
                        </article>
                      );
                    })}
                  </div>
                )}

                </div>

                <form className="composer" onSubmit={sendMessage}>
                  <input
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    placeholder={`Message ${activeChat.name}`}
                    aria-label="Type a message"
                  />

                  <div className="composer-actions">
                    <button
                      className="icon-button"
                      type="button"
                      aria-label="Attach file"
                    >
                      <Paperclip size={19} />
                    </button>

                    <button
                      className="icon-button"
                      type="button"
                      aria-label="Emoji"
                    >
                      <Smile size={19} />
                    </button>

                    <button
                      type="submit"
                      className="send-button"
                      disabled={!message.trim()}
                      aria-label="Send message"
                    >
                      <Send size={18} />
                    </button>
                  </div>
                </form>
              </>
            ) : (
              <div className="empty-conversation">
                <MessageCircle size={42} />
                <h2>Select a conversation</h2>
                <p>Choose a chat to get started.</p>
              </div>
            )}
          </section>
        ) : (
          <section className="conversation section-placeholder">
            <div className="empty-conversation">
              {activeNavigation === "Teams" && <Users size={42} />}
              {activeNavigation === "Activity" && <Activity size={42} />}
              {activeNavigation === "Calendar" && (
                <CalendarDays size={42} />
              )}
              {activeNavigation === "Calls" && <Phone size={42} />}

              <h2>{activeNavigation}</h2>
              <p>This section is a placeholder.</p>

              <button
                className="primary-button"
                onClick={() => setActiveNavigation("Chat")}
                type="button"
              >
                Open chat
              </button>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

export default App;
