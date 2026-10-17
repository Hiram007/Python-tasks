/* ==========================================================================
   Casidra prototype — interaction layer.
   Design prototype only: every action below updates the page in the browser
   and explicitly saves nothing. There is no backend call anywhere in this file.

   Contents: helpers, toasts, confirmation dialog, sidebar/drawer, dropdown
   menus, quick search, filterable tables, checklist sections, dialog/sheet
   forms with validation, and the live-reload hook for the dev server.
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

    $("[data-confirm-ok]", dialog).addEventListener("click", function () {
      var callback = pendingConfirm;
      var comment = $("#confirm-comment", dialog) ? $("#confirm-comment", dialog).value : "";
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
    if (options.askComment && options.commentLabel) {
      $(".field__label", extra).textContent = options.commentLabel;
    }

    var confirmButton = $("[data-confirm-ok]", dialog);
    confirmButton.textContent = options.confirmLabel || "Confirm";
    confirmButton.className = "btn " + (options.tone === "danger" ? "btn--danger" : "btn--primary");

    var iconWrap = $("[data-confirm-icon]", dialog);
    iconWrap.classList.toggle("dialog__icon--danger", options.tone === "danger");
    $("use", iconWrap).setAttribute("href", "#" + (options.icon || "i-help"));

    dialog.showModal();
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
    { type: "Cases", title: "Amara Okafor", meta: "Product Designer · Design · starts 3 Nov 2026", href: "case.html", icon: "i-user" },
    { type: "Cases", title: "Daniel Whitfield", meta: "Site Reliability Engineer · Technology · starts 27 Oct 2026", href: "cases.html", icon: "i-user" },
    { type: "Cases", title: "Chen Wei", meta: "Finance Analyst · Finance · overdue", href: "cases.html", icon: "i-user" },
    { type: "Cases", title: "Marcus Bennett", meta: "Facilities Supervisor · Facilities · starts 20 Oct 2026", href: "cases.html", icon: "i-user" },
    { type: "Tasks", title: "Accounts & access", meta: "IT · owner Tomás Ferreira · due 24 Oct 2026", href: "tasks.html", icon: "i-monitor" },
    { type: "Tasks", title: "Building access card", meta: "Facilities · owner Priya Raman · due 23 Oct 2026", href: "tasks.html", icon: "i-building" },
    { type: "Tasks", title: "Payroll enrolment", meta: "HR · owner Aisha Khan · overdue for Chen Wei", href: "tasks.html", icon: "i-briefcase" },
    { type: "Tasks", title: "Welcome announcement", meta: "Communications · owner Hannah Cole · due 27 Oct 2026", href: "tasks.html", icon: "i-megaphone" },
    { type: "Pages", title: "Onboarding dashboard", meta: "KPIs, cases in progress and approvals", href: "index.html", icon: "i-grid" },
    { type: "Pages", title: "All onboarding cases", meta: "Filter and sort every open case", href: "cases.html", icon: "i-users" },
    { type: "Pages", title: "Task queue", meta: "Cross-case tasks by due date and status", href: "tasks.html", icon: "i-check-list" },
    { type: "Pages", title: "Design system", meta: "Tokens, components and patterns", href: "design-system.html", icon: "i-palette" }
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
          '<p class="search__empty">No cases, people or tasks match “' + escapeHtml(query.trim()) +
          '”.<br>Try a name, a department or a task such as “access”.</p>';
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
      if (donutSvg) donutSvg.setAttribute("aria-label", percent + "% of onboarding tasks complete");
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
          commentLabel: "What needs to change?",
          onConfirm: function (comment) {
            toast(
              "Change request recorded",
              comment
                ? "“" + comment.slice(0, 90) + (comment.length > 90 ? "…" : "") + "” — not sent, prototype only."
                : "No comment added. Nothing was sent — design prototype only.",
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

  /* -- Approval queue ----------------------------------------------------- */
  function initApprovals() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-approve-request]");
      if (!button) return;
      var item = button.closest(".list__item") || button.closest("[data-approval-item]");
      confirmAction({
        title: "Approve this request?",
        sub: "In production the approval is written to the case audit trail.",
        body: (button.dataset.requestTitle || "This request") +
          (button.dataset.requestMeta ? " — " + button.dataset.requestMeta : "") +
          ". Nothing is saved in this design prototype.",
        confirmLabel: "Approve",
        icon: "i-check-circle",
        onConfirm: function () {
          var aside = item ? $(".list__aside", item) : null;
          if (aside) {
            aside.innerHTML = '<span class="badge badge--ok"><span class="badge__dot"></span>Approved</span>';
          }
          toast("Request approved", "Not saved — this is a design prototype.", "ok");
        }
      });
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

  /* -- "Mark ready for day one" with a guard for open tasks -------------- */
  function initReadyAction() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-mark-ready]");
      if (!button) return;

      var open = $$("[data-task-row]").filter(function (row) {
        var box = $(".task__box", row);
        return box && !box.checked;
      });

      if (open.length) {
        confirmAction({
          title: "Not ready for day one yet",
          sub: open.length + " tasks are still open across the four checklists.",
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
    initMenus();
    initSearch();
    initTables();
    initChecklists();
    initConfirmDialog();
    initApprovals();
    initRowActions();
    initReadyAction();
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

  window.casidraPrototype = { toast: toast, confirm: confirmAction };
})();
