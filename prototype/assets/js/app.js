/* ==========================================================================
   Casidra prototype — interaction layer.
   Design prototype only: every action below updates the page in the browser
   and explicitly saves nothing. There is no backend call anywhere in this file.

   Contents: helpers, toasts, the shared confirmation dialog, role switching,
   sidebar/drawer, dropdown menus, quick search, filterable tables, checklist
   sections, generic confirm triggers, approval decisions, dialog/sheet forms
   with validation, and the live-reload hook for the dev server.
   ========================================================================== */

(function () {
  "use strict";

  var $ = function (selector, root) {
    return (root || document).querySelector(selector);
  };
  var $$ = function (selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  };

  var DEPARTMENTS = {
    hr: { label: "HR", icon: "i-briefcase", className: "dept--hr" },
    it: { label: "IT", icon: "i-monitor", className: "dept--it" },
    facilities: { label: "Facilities", icon: "i-building", className: "dept--facilities" },
    comms: { label: "Communications", icon: "i-megaphone", className: "dept--comms" }
  };

  /* -- Roles -------------------------------------------------------------
     The prototype ships one shell and lets a reviewer switch the role, so the
     navigation, dashboards and actions each user group is designed for can be
     reviewed from a single build. `person` is the sample signed-in user for
     that role. This is a design device only: hiding a control is never a
     security control — Django enforces authorisation on the server. */
  var ROLES = {
    exec: {
      label: "Executive / management",
      person: { name: "Ines Duarte", job: "Chief Operating Officer", initials: "ID", avatar: "avatar--ink", email: "ines.duarte@casidra.example" }
    },
    hr: {
      label: "HR administrator",
      person: { name: "Rosa Bell", job: "People Operations Lead", initials: "RB", avatar: "avatar--ink", email: "rosa.bell@casidra.example" }
    },
    it: {
      label: "IT task owner",
      person: { name: "Tomás Ferreira", job: "IT Services Lead", initials: "TF", avatar: "avatar--amber", email: "tomas.ferreira@casidra.example" }
    },
    facilities: {
      label: "Facilities task owner",
      person: { name: "Priya Raman", job: "Facilities Coordinator", initials: "PR", avatar: "avatar--rose", email: "priya.raman@casidra.example" }
    },
    comms: {
      label: "Communications task owner",
      person: { name: "Hannah Cole", job: "Internal Communications", initials: "HC", avatar: "avatar--teal", email: "hannah.cole@casidra.example" }
    },
    manager: {
      label: "Line manager / approver",
      person: { name: "Nadia Haddad", job: "Head of Design", initials: "NH", avatar: "avatar--slate", email: "nadia.haddad@casidra.example" }
    },
    employee: {
      label: "Employee / coordinator",
      person: { name: "Amara Okafor", job: "Product Designer (arriving)", initials: "AO", avatar: "", email: "amara.okafor@casidra.example" }
    },
    admin: {
      label: "System administrator",
      person: { name: "Dev Sharma", job: "Systems Administrator", initials: "DS", avatar: "avatar--slate", email: "dev.sharma@casidra.example" }
    }
  };

  var DEFAULT_ROLE = "hr";

  function roleList(value) {
    return String(value || "").split(",").map(function (item) {
      return item.trim();
    }).filter(Boolean);
  }

  // Filled in by initChecklists and called again whenever tasks are added, so
  // the section and case progress always derive from the rendered rows.
  var refreshChecklists = function () {};

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  function formatDate(value) {
    if (!value) return "—";
    var date = new Date(value + "T00:00:00");
    if (isNaN(date.getTime())) return value;
    return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }

  /* -- Toasts ------------------------------------------------------------- */
  var TOAST_ICONS = { info: "i-info", ok: "i-check-circle", warn: "i-alert", danger: "i-alert" };

  function normaliseTone(tone) {
    return TOAST_ICONS[tone] ? tone : "info";
  }

  function toast(title, message, tone) {
    var host = $("#toasts");
    if (!host) return;
    tone = normaliseTone(tone);
    var element = document.createElement("div");
    element.className = "toast toast--" + tone;
    element.innerHTML =
      '<svg class="icon" aria-hidden="true"><use href="#' + TOAST_ICONS[tone] + '"/></svg>' +
      '<div class="grow"><p class="toast__title"></p><p class="toast__msg"></p></div>' +
      '<button class="toast__close" type="button" aria-label="Dismiss notification">' +
      '<svg class="icon icon--sm" aria-hidden="true"><use href="#i-close"/></svg></button>';
    $(".toast__title", element).textContent = title;
    if (message) {
      $(".toast__msg", element).textContent = message;
    } else {
      $(".toast__msg", element).remove();
    }
    host.appendChild(element);

    var remove = function () {
      element.classList.add("is-leaving");
      window.setTimeout(function () {
        element.remove();
      }, 240);
    };
    $(".toast__close", element).addEventListener("click", remove);
    window.setTimeout(remove, 7000);
  }

  /* -- Confirmation dialog ------------------------------------------------ */
  var pendingConfirm = null;

  function initConfirmDialog() {
    var dialog = $("#confirm-dialog");
    if (!dialog) return;

    function clearCommentError() {
      var error = $("[data-confirm-error]", dialog);
      var field = $("#confirm-comment", dialog);
      if (error) error.hidden = true;
      if (field) {
        field.removeAttribute("aria-invalid");
        var wrapper = field.closest(".field");
        if (wrapper) wrapper.classList.remove("has-error");
      }
    }

    $("[data-confirm-ok]", dialog).addEventListener("click", function () {
      var field = $("#confirm-comment", dialog);
      var comment = field ? field.value.trim() : "";

      // Some decisions (rejections, access removal exceptions) require a reason.
      if (dialog.dataset.requireComment === "true" && !comment) {
        var error = $("[data-confirm-error]", dialog);
        if (error) error.hidden = false;
        var wrapper = field.closest(".field");
        if (wrapper) wrapper.classList.add("has-error");
        field.setAttribute("aria-invalid", "true");
        field.focus();
        return;
      }

      var callback = pendingConfirm;
      pendingConfirm = null;
      dialog.close();
      if (callback) callback(comment);
    });

    $("[data-confirm-cancel]", dialog).addEventListener("click", function () {
      pendingConfirm = null;
      dialog.close();
    });

    dialog.addEventListener("close", function () {
      pendingConfirm = null;
      clearCommentError();
      if ($("#confirm-comment", dialog)) $("#confirm-comment", dialog).value = "";
    });

    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close();
    });
  }

  function confirmAction(options) {
    var dialog = $("#confirm-dialog");
    if (!dialog || typeof dialog.showModal !== "function") {
      if (options.onConfirm) options.onConfirm("");
      return;
    }
    pendingConfirm = options.onConfirm || null;

    $("[data-confirm-title]", dialog).textContent = options.title || "Confirm action";
    $("[data-confirm-sub]", dialog).textContent = options.sub || "Nothing is saved in this prototype.";
    $("[data-confirm-body]", dialog).textContent = options.body || "";

    var extra = $("[data-confirm-extra]", dialog);
    extra.hidden = !options.askComment;
    dialog.dataset.requireComment = options.requireComment ? "true" : "false";
    if (options.askComment && options.commentLabel) {
      $(".field__label", extra).textContent = options.commentLabel;
    }
    var error = $("[data-confirm-error]", dialog);
    if (error) error.hidden = true;

    var confirmButton = $("[data-confirm-ok]", dialog);
    confirmButton.textContent = options.confirmLabel || "Confirm";
    confirmButton.className = "btn " + (options.tone === "danger" ? "btn--danger" : "btn--primary");

    var iconWrap = $("[data-confirm-icon]", dialog);
    iconWrap.classList.toggle("dialog__icon--danger", options.tone === "danger");
    $("use", iconWrap).setAttribute("href", "#" + (options.icon || "i-help"));

    dialog.showModal();
  }

  /* -- Role switching ----------------------------------------------------- */
  function currentRole() {
    var stored = null;
    try {
      stored = window.sessionStorage.getItem("casidra.role");
    } catch (error) {
      stored = null;
    }
    return ROLES[stored] ? stored : DEFAULT_ROLE;
  }

  function applyRole(role) {
    if (!ROLES[role]) role = DEFAULT_ROLE;
    var person = ROLES[role].person;

    try {
      window.sessionStorage.setItem("casidra.role", role);
    } catch (error) {
      /* Session storage is a convenience; the shell still renders without it. */
    }

    document.documentElement.setAttribute("data-role", role);

    $$("[data-role-label]").forEach(function (element) {
      element.textContent = ROLES[role].label;
    });

    $$("[data-role-name]").forEach(function (element) {
      element.textContent = person.name;
    });

    // Sample signed-in user for the selected role, so the profile block and the
    // sidebar read as a real session rather than a fixed persona.
    $$("[data-user-name]").forEach(function (element) {
      element.textContent = person.name;
    });
    $$("[data-user-role]").forEach(function (element) {
      element.textContent = person.job;
    });
    $$("[data-user-email]").forEach(function (element) {
      element.textContent = person.email;
    });
    $$("[data-user-avatar]").forEach(function (element) {
      var size = element.classList.contains("avatar--lg") ? "avatar--lg"
        : element.classList.contains("avatar--xl") ? "avatar--xl"
        : element.classList.contains("avatar--sm") ? "avatar--sm" : "";
      element.className = ["avatar", person.avatar, size].filter(Boolean).join(" ");
      element.textContent = person.initials;
    });

    // Show only what the role is designed to see. `data-roles` lists the roles
    // allowed to see an element; `data-roles-except` lists the roles that must not.
    $$("[data-roles]").forEach(function (element) {
      element.hidden = roleList(element.dataset.roles).indexOf(role) === -1;
    });
    $$("[data-roles-except]").forEach(function (element) {
      element.hidden = roleList(element.dataset.rolesExcept).indexOf(role) !== -1;
    });

    $$("[data-role-set]").forEach(function (button) {
      var active = button.dataset.roleSet === role;
      button.classList.toggle("is-active", active);
      if (active) {
        button.setAttribute("aria-current", "true");
      } else {
        button.removeAttribute("aria-current");
      }
    });
  }

  function initRoles() {
    var role = currentRole();
    applyRole(role);

    $$("[data-role-set]").forEach(function (button) {
      button.addEventListener("click", function () {
        var next = button.dataset.roleSet;
        if (!ROLES[next]) return;
        applyRole(next);
        closeMenus();
        toast(
          "Viewing as " + ROLES[next].label,
          "Navigation and actions change for review only — authorisation is enforced by the Django backend.",
          "info"
        );
      });
    });
  }

  /* -- Sidebar and mobile drawer ------------------------------------------ */
  function initShell() {
    var app = $(".app");
    if (!app) return;
    var scrim = $(".scrim");

    function setNav(open) {
      app.classList.toggle("is-nav-open", open);
      $$("[data-nav-toggle]").forEach(function (button) {
        button.setAttribute("aria-expanded", String(open));
      });
      if (scrim) scrim.hidden = !open;
    }

    $$("[data-nav-toggle]").forEach(function (button) {
      button.addEventListener("click", function () {
        setNav(!app.classList.contains("is-nav-open"));
      });
    });

    $$("[data-nav-close]").forEach(function (button) {
      button.addEventListener("click", function () {
        setNav(false);
      });
    });

    $$("a.nav__item").forEach(function (link) {
      link.addEventListener("click", function () {
        setNav(false);
      });
    });

    var collapse = $("[data-sidebar-collapse]");
    if (collapse) {
      collapse.addEventListener("click", function () {
        var collapsed = app.classList.toggle("is-collapsed");
        collapse.setAttribute("aria-label", collapsed ? "Expand navigation" : "Collapse navigation");
      });
    }

    var page = document.body.dataset.page;
    if (page) {
      $$(".nav__item[data-nav]").forEach(function (link) {
        if (link.dataset.nav === page) {
          link.classList.add("is-active");
          link.setAttribute("aria-current", "page");
        }
      });
    }

    // Rows that link to a record: the primary cell holds a real link, and a
    // click anywhere else on the row follows it for mouse users.
    $$("[data-row-href]").forEach(function (row) {
      row.addEventListener("click", function (event) {
        if (event.target.closest("a, button, input, label, select")) return;
        window.location.href = row.dataset.rowHref;
      });
    });
  }

  /* -- Dropdown menus ----------------------------------------------------- */
  function closeMenus(except) {
    $$("[data-menu]").forEach(function (menu) {
      if (menu === except) return;
      var panel = $("[data-menu-panel]", menu);
      var trigger = $("[data-menu-trigger]", menu);
      if (panel) panel.hidden = true;
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    });
  }

  function initMenus() {
    $$("[data-menu]").forEach(function (menu) {
      var trigger = $("[data-menu-trigger]", menu);
      var panel = $("[data-menu-panel]", menu);
      if (!trigger || !panel) return;
      trigger.addEventListener("click", function (event) {
        event.stopPropagation();
        var willOpen = panel.hidden;
        closeMenus(menu);
        panel.hidden = !willOpen;
        trigger.setAttribute("aria-expanded", String(willOpen));
      });
      panel.addEventListener("click", function (event) {
        event.stopPropagation();
      });
    });

    document.addEventListener("click", function () {
      closeMenus();
    });

    $$("[data-notif-read-all]").forEach(function (button) {
      button.addEventListener("click", function () {
        $$(".notif.is-unread").forEach(function (item) {
          item.classList.remove("is-unread");
          item.classList.add("is-read");
          var label = $(".sr-only", item);
          if (label) label.textContent = "Read";
        });
        $$("[data-notif-item]").forEach(function (item) {
          item.dataset.unread = "false";
          if (item.hasAttribute("data-group")) item.setAttribute("data-group", "read");
        });
        var dot = $("[data-notif-dot]");
        if (dot) dot.hidden = true;
        var trigger = $("[data-notif-trigger]");
        if (trigger) trigger.setAttribute("aria-label", "Notifications, none unread");
        toast("Notifications marked as read", "Read state is not stored — this is a design prototype.", "ok");
      });
    });
  }

  /* -- Quick search ------------------------------------------------------- */
  var SEARCH_INDEX = [
    { type: "People", title: "Amara Okafor", meta: "Product Designer · Design · arrives 3 Nov 2026", href: "employee.html", icon: "i-user" },
    { type: "People", title: "Helena Marsh", meta: "Finance Business Partner · Finance · departs 30 Oct 2026", href: "departure.html", icon: "i-door" },
    { type: "People", title: "Raj Patel", meta: "Senior Data Engineer · Technology · departs 6 Nov 2026", href: "departure.html", icon: "i-door" },
    { type: "People", title: "Marcus Bennett", meta: "Facilities Supervisor · Facilities · starts 20 Oct 2026", href: "directory.html", icon: "i-user" },
    { type: "People", title: "Chen Wei", meta: "Finance Analyst · Finance · onboarding overdue", href: "case.html", icon: "i-user" },
    { type: "Cases", title: "ONB-2026-0148 · Amara Okafor", meta: "Onboarding case · Design · 47% ready", href: "case.html", icon: "i-users" },
    { type: "Cases", title: "DEP-2026-0031 · Helena Marsh", meta: "Departure case · Finance · 46% cleared", href: "departure.html", icon: "i-door" },
    { type: "Cases", title: "DEP-2026-0033 · Raj Patel", meta: "Departure case · Technology · 41% cleared", href: "offboarding.html", icon: "i-door" },
    { type: "Tasks", title: "Access groups & VPN", meta: "IT · owner Tomás Ferreira · blocked", href: "tasks.html", icon: "i-monitor" },
    { type: "Tasks", title: "Accounts & email deactivation", meta: "IT · Helena Marsh · due 30 Oct 2026", href: "departure.html", icon: "i-monitor" },
    { type: "Tasks", title: "Payroll enrolment", meta: "HR · owner Aisha Khan · overdue for Chen Wei", href: "tasks.html", icon: "i-briefcase" },
    { type: "Approvals", title: "Departure authorisation", meta: "Helena Marsh · raised by Aisha Khan · waiting 5 days", href: "approvals.html", icon: "i-inbox" },
    { type: "Approvals", title: "Entra ID access groups", meta: "Amara Okafor · raised by Tomás Ferreira", href: "approvals.html", icon: "i-shield" },
    { type: "Assets", title: "AST-1042 · Laptop", meta: "Helena Marsh · return outstanding", href: "equipment.html", icon: "i-monitor" },
    { type: "Pages", title: "Dashboard", meta: "Operational KPIs, approvals and upcoming dates", href: "index.html", icon: "i-grid" },
    { type: "Pages", title: "Employee directory", meta: "Searchable register of every employee", href: "directory.html", icon: "i-users" },
    { type: "Pages", title: "Departure cases", meta: "Offboarding, clearance and asset returns", href: "offboarding.html", icon: "i-door" },
    { type: "Pages", title: "Task queues", meta: "My tasks and the four departmental queues", href: "tasks.html", icon: "i-check-list" },
    { type: "Pages", title: "Approvals inbox", meta: "Pending decisions and approval history", href: "approvals.html", icon: "i-inbox" },
    { type: "Pages", title: "Equipment register", meta: "Assets, custody, handover and returns", href: "equipment.html", icon: "i-monitor" },
    { type: "Pages", title: "Notification centre", meta: "Alerts, reminders and delivery history", href: "notifications.html", icon: "i-bell" },
    { type: "Pages", title: "Reports & exports", meta: "Onboarding and offboarding performance", href: "reports.html", icon: "i-trend-up" },
    { type: "Pages", title: "Audit trail", meta: "Lifecycle, approval and administrative history", href: "audit.html", icon: "i-shield" },
    { type: "Pages", title: "Workflow templates", meta: "Checklists, dependencies and transitions", href: "workflows.html", icon: "i-settings" },
    { type: "Pages", title: "Users & roles", meta: "Accounts, roles, permissions and departments", href: "admin-users.html", icon: "i-shield" },
    { type: "Pages", title: "System settings", meta: "SSO, MFA, integrations and operational status", href: "admin-system.html", icon: "i-key" },
    { type: "Pages", title: "Design system", meta: "Tokens, components and patterns", href: "design-system.html", icon: "i-palette" },
    { type: "Pages", title: "Django handover", meta: "Pages, components, workflows and outstanding items", href: "handover.html", icon: "i-file" }
  ];

  function initSearch() {
    var input = $("[data-search-input]");
    var panel = $("[data-search-panel]");
    if (!input || !panel) return;

    function close() {
      panel.hidden = true;
      input.setAttribute("aria-expanded", "false");
    }

    function render(query) {
      var term = query.trim().toLowerCase();
      if (!term) {
        close();
        return;
      }
      var matches = SEARCH_INDEX.filter(function (item) {
        return (item.title + " " + item.meta).toLowerCase().indexOf(term) !== -1;
      }).slice(0, 9);

      if (!matches.length) {
        panel.innerHTML =
          '<p class="search__empty">Nothing matches “' + escapeHtml(query.trim()) +
          '”.<br>Try a person, a case number, a department or a task such as “access”.</p>';
      } else {
        var groups = [];
        matches.forEach(function (item) {
          var group = groups.filter(function (candidate) { return candidate.type === item.type; })[0];
          if (!group) {
            group = { type: item.type, items: [] };
            groups.push(group);
          }
          group.items.push(item);
        });

        panel.innerHTML = groups.map(function (group) {
          return '<p class="search__group-label">' + escapeHtml(group.type) + "</p>" +
            group.items.map(function (item) {
              return '<button class="search__result" type="button" role="option" aria-selected="false" data-search-href="' +
                escapeHtml(item.href) + '">' +
                '<span class="search__result-icon"><svg class="icon icon--sm" aria-hidden="true"><use href="#' +
                escapeHtml(item.icon) + '"/></svg></span>' +
                '<span class="grow"><span class="search__result-title">' + escapeHtml(item.title) + "</span><br>" +
                '<span class="search__result-meta">' + escapeHtml(item.meta) + "</span></span>" +
                '<svg class="icon icon--sm" aria-hidden="true"><use href="#i-arrow-right"/></svg>' +
                "</button>";
            }).join("");
        }).join("");
      }

      panel.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }

    input.addEventListener("input", function () {
      render(input.value);
    });

    input.addEventListener("focus", function () {
      if (input.value.trim()) render(input.value);
    });

    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        input.value = "";
        close();
        return;
      }
      if (event.key === "Enter") {
        var first = $("[data-search-href]", panel);
        if (first) {
          event.preventDefault();
          window.location.href = first.dataset.searchHref;
        }
      }
    });

    panel.addEventListener("click", function (event) {
      var result = event.target.closest("[data-search-href]");
      if (result) window.location.href = result.dataset.searchHref;
    });

    panel.addEventListener("click", function (event) {
      event.stopPropagation();
    });

    document.addEventListener("click", function (event) {
      if (!event.target.closest(".search")) close();
    });

    document.addEventListener("keydown", function (event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        input.focus();
        input.select();
      }
    });
  }

  /* -- Filterable tables -------------------------------------------------- */
  function initTables() {
    $$("[data-table-region]").forEach(function (region) {
      var rows = $$("[data-table-rows] tr[data-search]", region);
      if (!rows.length) return;

      var search = $("[data-table-search]", region);
      var filters = $$("[data-table-filter]", region);
      var empty = $("[data-table-empty]", region);
      var tableWrap = $("[data-table-wrap]", region);
      var count = $("[data-table-count]", region);
      var noun = region.dataset.countNoun || "cases";
      var groupButtons = $$("[data-group-value]", region);
      var activeGroup = "all";
      var total = rows.length;

      function apply() {
        var term = search ? search.value.trim().toLowerCase() : "";
        var visible = 0;

        rows.forEach(function (row) {
          var matches = !term || (row.dataset.search || "").indexOf(term) !== -1;
          if (matches) {
            filters.forEach(function (filter) {
              var value = filter.value;
              if (value && row.dataset[filter.dataset.tableFilter] !== value) matches = false;
            });
          }
          if (matches && activeGroup !== "all" && row.dataset.group !== activeGroup) matches = false;
          row.hidden = !matches;
          if (matches) visible += 1;
        });

        if (tableWrap) tableWrap.hidden = visible === 0;
        if (empty) empty.hidden = visible !== 0;
        if (count) {
          count.textContent = visible === total
            ? "Showing all " + total + " " + noun
            : "Showing " + visible + " of " + total + " " + noun;
        }
      }

      if (search) {
        search.addEventListener("input", apply);
      }

      filters.forEach(function (filter) {
        filter.addEventListener("change", apply);
      });

      groupButtons.forEach(function (button) {
        button.addEventListener("click", function () {
          groupButtons.forEach(function (candidate) {
            candidate.setAttribute("aria-selected", String(candidate === button));
          });
          activeGroup = button.dataset.groupValue;
          apply();
        });
      });

      $$("[data-table-reset]", region).forEach(function (reset) {
        reset.addEventListener("click", function () {
          if (search) search.value = "";
          filters.forEach(function (filter) {
            filter.value = "";
          });
          groupButtons.forEach(function (button, index) {
            button.setAttribute("aria-selected", String(index === 0));
          });
          activeGroup = "all";
          apply();
        });
      });

      apply();
    });
  }

  /* -- Checklist sections ------------------------------------------------- */
  function applyRowState(row, done) {
    var badge = $("[data-task-status]", row);
    row.classList.toggle("is-done", done);
    if (!badge) return;
    if (done) {
      badge.className = "badge badge--ok";
      badge.innerHTML = '<span class="badge__dot"></span>Complete';
    } else {
      badge.className = row.dataset.statusClass || "badge";
      badge.innerHTML = '<span class="badge__dot"></span>' + (row.dataset.statusText || "Not started");
    }
  }

  function initChecklists() {
    var sections = $$("[data-checklist]");
    if (!sections.length) return;

    $$("[data-task-row]").forEach(function (row) {
      var badge = $("[data-task-status]", row);
      if (!badge) return;
      row.dataset.statusClass = badge.className;
      row.dataset.statusText = badge.textContent.trim();
    });

    function recompute() {
      var allRows = $$("[data-task-row]");

      sections.forEach(function (section) {
        var rows = allRows.filter(function (row) { return section.contains(row); });
        var done = rows.filter(function (row) { return $(".task__box", row) && $(".task__box", row).checked; }).length;
        var percent = rows.length ? Math.round((done / rows.length) * 100) : 0;

        var countLabel = $("[data-section-count]", section);
        if (countLabel) countLabel.textContent = done + " of " + rows.length + " complete";

        var fill = $("[data-section-fill]", section);
        if (fill) fill.style.width = percent + "%";

        var value = $("[data-section-value]", section);
        if (value) value.textContent = percent + "%";
      });

      // Per-department summary counts ([data-dept-count="hr"]) stay in step with
      // their checklist section, so a readiness or clearance summary can never
      // disagree with the checklist it is derived from.
      $$("[data-dept-count]").forEach(function (label) {
        var section = $('[data-checklist][data-department="' + label.dataset.deptCount + '"]');
        if (!section) return;
        var rows = allRows.filter(function (row) { return section.contains(row); });
        var complete = rows.filter(function (row) {
          return $(".task__box", row) && $(".task__box", row).checked;
        }).length;
        label.textContent = complete + " / " + rows.length;
      });

      var done = allRows.filter(function (row) { return $(".task__box", row) && $(".task__box", row).checked; }).length;
      var percent = allRows.length ? Math.round((done / allRows.length) * 100) : 0;
      var radius = 18;
      var circumference = 2 * Math.PI * radius;

      var overallFill = $("[data-overall-fill]");
      if (overallFill) overallFill.style.width = percent + "%";

      var overallValue = $("[data-overall-value]");
      if (overallValue) overallValue.textContent = percent + "%";

      var overallCount = $("[data-overall-count]");
      if (overallCount) overallCount.textContent = done + " of " + allRows.length + " tasks complete";

      var donut = $("[data-overall-donut]");
      if (donut) {
        donut.style.strokeDasharray = String(circumference);
        donut.style.strokeDashoffset = String(circumference * (1 - percent / 100));
      }

      var donutSvg = $("[data-overall-donut-svg]");
      if (donutSvg) donutSvg.setAttribute("aria-label", percent + "% of case tasks complete");
    }

    refreshChecklists = recompute;

    sections.forEach(function (section) {
      section.addEventListener("change", function (event) {
        var box = event.target.closest(".task__box");
        if (!box) return;
        applyRowState(box.closest("[data-task-row]"), box.checked);
        recompute();
      });
    });

    $$("[data-task-row]").forEach(function (row) {
      var box = $(".task__box", row);
      if (box && box.checked) applyRowState(row, true);
    });

    recompute();

    document.addEventListener("click", function (event) {
      var approve = event.target.closest("[data-task-approve]");
      if (approve) {
        var row = approve.closest("[data-task-row]");
        var title = $(".task__title", row) ? $(".task__title", row).textContent.trim() : "this step";
        confirmAction({
          title: "Approve this step?",
          sub: "Recorded against the case audit trail in the production system.",
          body: "Approving “" + title + "” marks the step complete and notifies the responsible department. In this prototype nothing is saved or sent.",
          confirmLabel: "Approve step",
          icon: "i-check-circle",
          onConfirm: function () {
            var box = $(".task__box", row);
            if (box && !box.checked) {
              box.checked = true;
              box.dispatchEvent(new Event("change", { bubbles: true }));
            }
            approve.hidden = true;
            toast("Step approved", "Approval is not saved — this is a design prototype.", "ok");
          }
        });
        return;
      }

      var request = event.target.closest("[data-task-request-changes]");
      if (request) {
        confirmAction({
          title: "Request changes",
          sub: "The task owner is notified in the production system.",
          body: "Describe what needs to change before this step can be approved. No message is sent from this prototype.",
          confirmLabel: "Send request",
          icon: "i-refresh",
          askComment: true,
          requireComment: true,
          commentLabel: "What needs to change?",
          onConfirm: function (comment) {
            toast(
              "Change request recorded",
              "“" + comment.slice(0, 90) + (comment.length > 90 ? "…" : "") + "” — not sent, prototype only.",
              "warn"
            );
          }
        });
      }
    });
  }

  /* -- Sheet forms with validation --------------------------------------- */
  function setFieldError(field, message) {
    var wrapper = field.closest(".field");
    if (!wrapper) return;
    var error = $(".field__error", wrapper);

    if (!message) {
      wrapper.classList.remove("has-error");
      field.removeAttribute("aria-invalid");
      if (error) error.remove();
      return;
    }

    wrapper.classList.add("has-error");
    field.setAttribute("aria-invalid", "true");
    if (!error) {
      error = document.createElement("p");
      error.className = "field__error";
      error.innerHTML =
        '<svg class="icon icon--sm" aria-hidden="true"><use href="#i-alert"/></svg><span></span>';
      wrapper.appendChild(error);
    }
    $("span", error).textContent = message;
    if (!error.id) error.id = (field.id || field.name || "field") + "-error";
    field.setAttribute("aria-describedby", error.id);
  }

  function validateField(field) {
    var value = (field.value || "").trim();
    var message = "";

    if (field.required && !value) {
      message = field.dataset.requiredMessage || "This field is required.";
    } else if (value && field.type === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      message = "Enter a valid email address, for example name@casidra.example.";
    } else if (value && field.dataset.minDate && value < field.dataset.minDate) {
      message = "Choose a date on or after " + formatDate(field.dataset.minDate) + ".";
    }

    setFieldError(field, message);
    return !message;
  }

  function validateForm(form) {
    var fields = $$("[data-validate]", form).filter(function (field) {
      return !field.disabled;
    });
    var invalid = fields.filter(function (field) {
      return !validateField(field);
    });

    var summary = $("[data-form-summary]", form);
    if (summary) {
      summary.hidden = invalid.length === 0;
      var text = $("[data-form-summary-text]", summary);
      if (text && invalid.length) {
        text.textContent = invalid.length === 1
          ? "1 field needs attention before you can continue."
          : invalid.length + " fields need attention before you can continue.";
      }
    }

    if (invalid.length) invalid[0].focus();
    return invalid;
  }

  function clearForm(form) {
    $$("[data-validate]", form).forEach(function (field) {
      setFieldError(field, "");
    });
    var summary = $("[data-form-summary]", form);
    if (summary) summary.hidden = true;
  }

  function handleNewCase(form) {
    var name = $("#case-employee", form).value.trim();
    var department = $("#case-department", form).value;
    var start = $("#case-start", form).value;
    var coordinator = $("#case-coordinator", form).value;

    confirmAction({
      title: "Create this onboarding case?",
      sub: "In production this opens the case and assigns the departmental checklists.",
      body: name + " · " + department + " · starts " + formatDate(start) + " · coordinator " + coordinator +
        ". Nothing is created in this prototype.",
      confirmLabel: "Create case",
      icon: "i-plus",
      onConfirm: function () {
        var sheet = form.closest("dialog");
        if (sheet) sheet.close();
        form.reset();
        toast("Onboarding case prepared", "Not saved — connect this form to the Django endpoint to persist it.", "ok");
      }
    });
  }

  function handleNewDeparture(form) {
    var name = $("#departure-employee", form).value.trim();
    var lastDay = $("#departure-last-day", form).value;
    var reason = $("#departure-reason", form).value;
    var notice = $("#departure-notice", form).value;

    confirmAction({
      title: "Open this departure case?",
      sub: "In production this creates the case and assigns the clearance checklists.",
      body: name + " · last day " + formatDate(lastDay) + " · reason " + reason + " · notice received " +
        formatDate(notice) + ". Nothing is created in this prototype.",
      confirmLabel: "Open departure case",
      icon: "i-door",
      onConfirm: function () {
        var sheet = form.closest("dialog");
        if (sheet) sheet.close();
        form.reset();
        toast("Departure case prepared", "Not saved — connect this form to the Django endpoint to persist it.", "ok");
      }
    });
  }

  function handleAddTask(form) {
    var sheet = form.closest("dialog");
    var departmentKey = $("#task-department", form).value;
    var department = DEPARTMENTS[departmentKey] || DEPARTMENTS.hr;
    var section = $('[data-checklist][data-department="' + departmentKey + '"]');
    var title = $("#task-title", form).value.trim();
    var owner = $("#task-owner", form).value;
    var due = $("#task-due", form).value;
    var notes = $("#task-notes", form).value.trim();

    confirmAction({
      title: "Add this task?",
      sub: "The task appears in the " + department.label + " checklist.",
      body: title + " · owner " + owner + " · due " + formatDate(due) +
        ". Added in the browser only — nothing is saved in this prototype.",
      confirmLabel: "Add task",
      icon: "i-plus",
      onConfirm: function () {
        var template = $("#task-template");
        if (template && section) {
          var id = "task-" + departmentKey + "-" + Date.now();
          var markup = template.innerHTML
            .replace(/__ID__/g, id)
            .replace("__TITLE__", escapeHtml(title))
            .replace("__DESC__", escapeHtml(notes || "Added from the prototype task form."))
            .replace("__OWNER__", escapeHtml(owner))
            .replace("__DUE__", escapeHtml(formatDate(due)))
            .replace("__DEPT_CLASS__", department.className)
            .replace(/__DEPT_ICON__/g, department.icon)
            .replace("__DEPT_LABEL__", department.label);
          var holder = document.createElement("div");
          holder.innerHTML = markup.trim();
          var row = holder.firstElementChild;
          if (row) {
            var badge = $("[data-task-status]", row);
            if (badge) {
              row.dataset.statusClass = badge.className;
              row.dataset.statusText = badge.textContent.trim();
            }
            var list = $(".checklist", section);
            if (list) list.appendChild(row);
          }
        }
        if (sheet) sheet.close();
        form.reset();
        refreshChecklists();
        toast("Task added to " + department.label, "Held in the page only — wire it to Django to persist it.", "ok");
      }
    });
  }

  var SHEET_HANDLERS = {
    "new-case": handleNewCase,
    "new-departure": handleNewDeparture,
    "add-task": handleAddTask
  };

  function initSheets() {
    $$("[data-sheet-open]").forEach(function (button) {
      button.addEventListener("click", function () {
        var sheet = document.getElementById(button.dataset.sheetOpen);
        if (!sheet) return;
        var form = $("form", sheet);
        if (form) {
          clearForm(form);
          if (button.dataset.department && $("#task-department", form)) {
            $("#task-department", form).value = button.dataset.department;
          }
        }
        sheet.showModal();
      });
    });

    $$("[data-sheet-close]").forEach(function (button) {
      button.addEventListener("click", function () {
        var sheet = button.closest("dialog");
        if (sheet) sheet.close();
      });
    });

    $$(".sheet").forEach(function (sheet) {
      var form = $("form", sheet);
      if (!form) return;

      $$("[data-validate]", form).forEach(function (field) {
        field.addEventListener("blur", function () {
          validateField(field);
        });
        field.addEventListener("input", function () {
          var wrapper = field.closest(".field");
          if (wrapper && wrapper.classList.contains("has-error")) validateField(field);
        });
        field.addEventListener("change", function () {
          if (field.tagName === "SELECT" || field.type === "date") validateField(field);
        });
      });

      form.addEventListener("submit", function (event) {
        event.preventDefault();
        if (validateForm(form).length) return;
        var handler = SHEET_HANDLERS[form.dataset.sheetForm];
        if (handler) handler(form);
      });

      sheet.addEventListener("close", function () {
        clearForm(form);
      });
    });
  }

  /* -- Generic confirm triggers ------------------------------------------
     Any control can drive the shared dialog declaratively:
       data-confirm, data-confirm-title, -sub, -body, -label, -tone, -icon,
       data-confirm-comment="label"  (shows the comment box; add
       data-confirm-require-comment to make it mandatory),
       data-confirm-status="Approved|ok" (writes a badge into the row),
       data-confirm-hide (removes the trigger once confirmed),
       data-confirm-toast, -toast-message, -toast-tone. */
  function writeStatusBadge(scope, spec) {
    if (!scope) return;
    var parts = String(spec).split("|");
    var text = parts[0].trim();
    var tone = (parts[1] || "ok").trim();
    var host = scope.querySelector("[data-row-status], [data-decision-target], [data-confirm-target]");
    if (!host) return;
    host.innerHTML = '<span class="badge badge--' + tone + '"><span class="badge__dot"></span>' +
      escapeHtml(text) + "</span>";
  }

  function initConfirmTriggers() {
    document.addEventListener("click", function (event) {
      var trigger = event.target.closest("[data-confirm]");
      if (!trigger) return;
      event.preventDefault();

      var scope = trigger.closest("tr, li, article, section, .list__item") || trigger.parentElement;
      confirmAction({
        title: trigger.dataset.confirmTitle || "Confirm action",
        sub: trigger.dataset.confirmSub || "Recorded in the production system — nothing is saved here.",
        body: trigger.dataset.confirmBody || "",
        confirmLabel: trigger.dataset.confirmLabel || "Confirm",
        tone: trigger.dataset.confirmTone || "primary",
        icon: trigger.dataset.confirmIcon || "i-help",
        askComment: Boolean(trigger.dataset.confirmComment),
        requireComment: trigger.hasAttribute("data-confirm-require-comment"),
        commentLabel: trigger.dataset.confirmComment || "",
        onConfirm: function (comment) {
          if (trigger.dataset.confirmStatus) writeStatusBadge(scope, trigger.dataset.confirmStatus);
          if (trigger.hasAttribute("data-confirm-hide")) trigger.hidden = true;
          var message = trigger.dataset.confirmToastMessage;
          if (!message) {
            message = comment
              ? "“" + comment.slice(0, 90) + (comment.length > 90 ? "…" : "") + "” — not sent, prototype only."
              : "Nothing is saved — this is a design prototype.";
          }
          toast(trigger.dataset.confirmToast || "Action recorded", message, trigger.dataset.confirmToastTone || "ok");
        }
      });
    });
  }

  /* -- Approval decisions (approve / reject / return) --------------------- */
  var DECISIONS = {
    approve: {
      title: "Approve this request?",
      sub: "In production the decision is written to the case audit trail with your name and a timestamp.",
      confirmLabel: "Approve",
      icon: "i-check-circle",
      askComment: true,
      commentLabel: "Comment (optional)",
      status: "Approved|ok",
      toast: "Request approved"
    },
    reject: {
      title: "Reject this request?",
      sub: "A rejection is recorded against the case and the requester is notified in the production system.",
      confirmLabel: "Reject request",
      icon: "i-alert",
      tone: "danger",
      askComment: true,
      requireComment: true,
      commentLabel: "Reason for rejection (required)",
      status: "Rejected|danger",
      toast: "Request rejected"
    },
    return: {
      title: "Return for correction?",
      sub: "The request goes back to the requester with your comment in the production system.",
      confirmLabel: "Return for correction",
      icon: "i-refresh",
      askComment: true,
      requireComment: true,
      commentLabel: "What needs correcting? (required)",
      status: "Returned|warn",
      toast: "Returned for correction"
    }
  };

  function initDecisions() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-decision]");
      if (!button) return;
      var spec = DECISIONS[button.dataset.decision];
      if (!spec) return;

      var scope = button.closest("tr, li, article, .list__item") || button.parentElement;
      var target = button.dataset.requestTitle || "this request";
      var meta = button.dataset.requestMeta ? " — " + button.dataset.requestMeta : "";

      confirmAction({
        title: spec.title,
        sub: spec.sub,
        body: button.dataset.decisionBody ||
          target + meta + ". Nothing is saved in this design prototype.",
        confirmLabel: spec.confirmLabel,
        tone: spec.tone || "primary",
        icon: spec.icon,
        askComment: spec.askComment,
        requireComment: spec.requireComment,
        commentLabel: spec.commentLabel,
        onConfirm: function (comment) {
          writeStatusBadge(scope, spec.status);
          var actions = scope ? scope.querySelector("[data-decision-actions]") : null;
          if (actions) actions.hidden = true;
          toast(
            spec.toast,
            comment ? "Comment recorded: “" + comment.slice(0, 80) + (comment.length > 80 ? "…" : "") + "” — prototype only."
              : "Not saved — this is a design prototype.",
            button.dataset.decision === "approve" ? "ok" : "warn"
          );
        }
      });
    });
  }

  /* -- Notification read state ------------------------------------------- */
  function initNotifRows() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-notif-toggle]");
      if (!button) return;
      var item = button.closest("[data-notif-item]");
      if (!item) return;

      var nowRead = item.dataset.unread !== "false";
      item.dataset.unread = String(!nowRead);
      item.classList.toggle("is-unread", !nowRead);
      item.classList.toggle("is-read", nowRead);
      if (item.hasAttribute("data-group")) item.setAttribute("data-group", nowRead ? "read" : "unread");

      var state = $("[data-notif-state]", item);
      if (state) {
        state.innerHTML = nowRead
          ? '<span class="badge"><span class="badge__dot"></span>Read</span>'
          : '<span class="badge badge--brand"><span class="badge__dot"></span>Unread</span>';
      }
      button.textContent = nowRead ? "Mark as unread" : "Mark as read";
      toast("Notification updated", "Read state is not stored — this is a design prototype.", "info");
    });
  }

  /* -- Table row actions (task queue) ------------------------------------ */
  function initRowActions() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-row-action]");
      if (!button) return;
      var row = button.closest("tr");
      var task = button.dataset.rowTask || "this task";
      var approving = button.dataset.rowAction === "approve";
      confirmAction({
        title: approving ? "Approve this step?" : "Mark this task complete?",
        sub: approving
          ? "In production the approval is written to the case audit trail."
          : "Completing a task moves the case readiness score forward.",
        body: "“" + task + "”. Nothing is saved in this design prototype.",
        confirmLabel: approving ? "Approve step" : "Mark complete",
        icon: "i-check-circle",
        onConfirm: function () {
          var status = row ? $("[data-row-status]", row) : null;
          if (status) {
            status.innerHTML = '<span class="badge badge--ok"><span class="badge__dot"></span>Complete</span>';
          }
          button.remove();
          toast(
            approving ? "Step approved" : "Task marked complete",
            "Not saved — this is a design prototype.",
            "ok"
          );
        }
      });
    });
  }

  /* -- Guarded case-level actions --------------------------------------- */
  function openTasks() {
    var rows = $$("[data-task-row]").filter(function (row) {
      var box = $(".task__box", row);
      return box && !box.checked;
    });
    return rows.length;
  }

  function initReadyAction() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-mark-ready]");
      if (!button) return;

      var open = openTasks();
      if (open) {
        confirmAction({
          title: "Not ready for day one yet",
          sub: open + " tasks are still open across the four checklists.",
          body: "Clear or approve the remaining tasks — including the blocked access group — before marking " +
            "this case ready. Nothing is saved in this prototype.",
          confirmLabel: "Review open tasks",
          icon: "i-alert",
          onConfirm: function () {
            if (window.location.hash !== "#checklists") window.location.hash = "#checklists";
          }
        });
        return;
      }

      confirmAction({
        title: "Mark this case ready for day one?",
        sub: "The coordinator confirms every departmental checklist is signed off.",
        body: "Amara Okafor starts Tue 3 Nov 2026. In production this notifies HR, IT, Facilities and " +
          "Communications. Nothing is saved in this prototype.",
        confirmLabel: "Mark ready",
        icon: "i-check-circle",
        onConfirm: function () {
          toast("Case marked ready", "Nothing is saved — this is a design prototype.", "ok");
        }
      });
    });
  }

  function initClearanceAction() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-mark-clear]");
      if (!button) return;

      var open = openTasks();
      if (open) {
        confirmAction({
          title: "Not fully cleared yet",
          sub: open + " clearance actions are still outstanding or awaiting approval.",
          body: "Final clearance for Helena Marsh (DEP-2026-0031) cannot be recorded while departmental " +
            "actions and asset returns are open. Nothing is saved in this prototype.",
          confirmLabel: "Review outstanding actions",
          icon: "i-alert",
          onConfirm: function () {
            if (window.location.hash !== "#clearance") window.location.hash = "#clearance";
          }
        });
        return;
      }

      confirmAction({
        title: "Record final clearance?",
        sub: "This closes the departure case and writes the clearance summary to the audit trail.",
        body: "Helena Marsh departs Fri 30 Oct 2026. In production this notifies HR, IT, Facilities, " +
          "Communications and the line manager. Nothing is saved in this prototype.",
        confirmLabel: "Record clearance",
        icon: "i-check-circle",
        onConfirm: function () {
          toast("Final clearance recorded", "Nothing is saved — this is a design prototype.", "ok");
        }
      });
    });
  }

  /* -- Design-system page demo ------------------------------------------- */
  function initDesignSystemDemo() {
    var button = $("#ds-demo-confirm");
    if (!button) return;
    button.addEventListener("click", function () {
      confirmAction({
        title: "Approve this step?",
        sub: "The shared confirmation dialog.",
        body: "The same dialog confirms approvals, destructive actions and guarded actions such as marking a " +
          "case ready while tasks are still open. Nothing is saved in this prototype.",
        confirmLabel: "Approve step",
        icon: "i-check-circle",
        onConfirm: function () {
          toast("Step approved", "Not saved — this is a design prototype.", "ok");
        }
      });
    });
  }

  /* -- Generic prototype toasts ------------------------------------------ */
  function initToastTriggers() {
    document.addEventListener("click", function (event) {
      var trigger = event.target.closest("[data-toast]");
      if (!trigger) return;
      event.preventDefault();
      toast(
        trigger.dataset.toast,
        trigger.dataset.toastMessage || "This is a design prototype — nothing is saved or sent.",
        trigger.dataset.toastTone || "info"
      );
    });
  }

  /* -- Escape closes transient UI ---------------------------------------- */
  function initEscape() {
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      closeMenus();
      var app = $(".app");
      if (app && app.classList.contains("is-nav-open")) {
        app.classList.remove("is-nav-open");
        var scrim = $(".scrim");
        if (scrim) scrim.hidden = true;
        $$("[data-nav-toggle]").forEach(function (button) {
          button.setAttribute("aria-expanded", "false");
        });
      }
    });
  }

  /* -- Live reload (dev server only) ------------------------------------- */
  function initLiveReload() {
    if (!window.EventSource) return;
    try {
      var stream = new EventSource("/__reload");
      stream.addEventListener("message", function (event) {
        if (event.data === "reload") window.location.reload();
      });
    } catch (error) {
      /* Live reload is a development convenience; the pages work without it. */
    }
  }

  function init() {
    initShell();
    initRoles();
    initMenus();
    initSearch();
    initTables();
    initChecklists();
    initConfirmDialog();
    initConfirmTriggers();
    initDecisions();
    initNotifRows();
    initRowActions();
    initReadyAction();
    initClearanceAction();
    initSheets();
    initDesignSystemDemo();
    initToastTriggers();
    initEscape();
    initLiveReload();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.casidraPrototype = { toast: toast, confirm: confirmAction, applyRole: applyRole };
})();
