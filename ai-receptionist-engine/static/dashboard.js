"use strict";

/* =========================================================
   TRIMTECH GARAGE AI DASHBOARD
   File: static/js/dashboard.js

   This file controls:
   - Mobile navigation
   - Dashboard refresh
   - Booking statistics
   - Upcoming appointment table
   - Seven-day booking chart
   - Service performance
   - Reminder health
   - Recent AI activity
   - System connection status
   - Toast messages
   ========================================================= */


/* =========================================================
   1. API ENDPOINTS

   We will create these Flask routes in the backend file later.
   The dashboard will remain usable before those routes exist.
   ========================================================= */

const API_ENDPOINTS = {
    dashboard: "/api/dashboard-data",
    runReminders: "/api/run-reminders"
};


/* =========================================================
   2. SERVICE AND ACTIVITY ICONS
   ========================================================= */

const SERVICE_ICONS = {
    mot: "✅",
    "full service": "🔧",
    service: "🔧",
    diagnostic: "🔍",
    "oil change": "🛢️"
};

const ACTIVITY_ICONS = {
    call: "📞",
    phone: "📞",
    booking: "📅",
    booked: "📅",
    appointment: "📅",
    cancel: "✕",
    cancelled: "✕",
    reschedule: "↻",
    rescheduled: "↻",
    reminder: "🔔",
    vehicle: "🚗",
    dvla: "🚘",
    customer: "👤",
    lookup: "🔍",
    ai: "🤖"
};


/* =========================================================
   3. DEFAULT DASHBOARD DATA

   These values allow the page to load safely before the
   Flask dashboard API has been connected.
   ========================================================= */

function getDefaultDashboardData() {
    return {
        summary: {
            today_bookings: 0,
            upcoming_bookings: 0,
            reminders_due: 0,
            estimated_revenue: 0,
            total_customers: 0
        },

        next_appointment: null,

        booking_activity: [],

        service_performance: [
            {
                name: "MOT",
                bookings: 0
            },
            {
                name: "Full Service",
                bookings: 0
            },
            {
                name: "Diagnostic",
                bookings: 0
            },
            {
                name: "Oil Change",
                bookings: 0
            }
        ],

        upcoming_appointments: [],

        reminders: {
            enabled: true,
            due: 0,
            sent_this_month: 0,
            last_run: null,
            status: "ready"
        },

        ai_activity: [],

        systems: {
            overall: "operational",
            vapi: "connected",
            calendar: "connected",
            dvla: "connected",
            backend: "connected"
        }
    };
}


/* =========================================================
   4. DASHBOARD STATE
   ========================================================= */

const dashboardState = {
    data: getDefaultDashboardData(),
    loading: false,
    remindersRunning: false
};


/* =========================================================
   5. PAGE ELEMENTS
   ========================================================= */

const dashboardElements = {};

function loadDashboardElements() {
    dashboardElements.sidebar =
        document.getElementById("dashboardSidebar");

    dashboardElements.mobileOverlay =
        document.getElementById("mobileOverlay");

    dashboardElements.menuButton =
        document.getElementById("menuButton");

    dashboardElements.refreshButton =
        document.getElementById("refreshDashboardButton");

    dashboardElements.runRemindersButton =
        document.getElementById("runRemindersButton");

    dashboardElements.headerDate =
        document.getElementById("headerDate");

    dashboardElements.todayBookings =
        document.getElementById("todayBookingsMetric");

    dashboardElements.upcomingBookings =
        document.getElementById("upcomingBookingsMetric");

    dashboardElements.remindersDue =
        document.getElementById("remindersDueMetric");

    dashboardElements.revenue =
        document.getElementById("revenueMetric");

    dashboardElements.navigationBookingCount =
        document.getElementById("navigationBookingCount");

    dashboardElements.navigationReminderCount =
        document.getElementById("navigationReminderCount");

    dashboardElements.nextAppointmentTime =
        document.getElementById("nextAppointmentTime");

    dashboardElements.nextAppointmentDetail =
        document.getElementById("nextAppointmentDetail");

    dashboardElements.chartTotalBookings =
        document.getElementById("chartTotalBookings");

    dashboardElements.servicePerformanceList =
        document.getElementById("servicePerformanceList");

    dashboardElements.bookingsTableBody =
        document.getElementById("upcomingBookingsTableBody");

    dashboardElements.reminderSystemBadge =
        document.getElementById("reminderSystemBadge");

    dashboardElements.schedulerLastRun =
        document.getElementById("schedulerLastRun");

    dashboardElements.schedulerStatus =
        document.getElementById("schedulerStatus");

    dashboardElements.remindersWaiting =
        document.getElementById("remindersWaitingValue");

    dashboardElements.remindersSent =
        document.getElementById("remindersSentValue");

    dashboardElements.remindersSentDetail =
        document.getElementById("remindersSentDetail");

    dashboardElements.aiActivityList =
        document.getElementById("aiActivityList");

    dashboardElements.totalCustomers =
        document.getElementById("totalCustomersLabel");

    dashboardElements.overallSystemStatus =
        document.getElementById("overallSystemStatus");

    dashboardElements.sidebarStatusText =
        document.getElementById("sidebarStatusText");

    dashboardElements.sidebarStatusDetail =
        document.getElementById("sidebarStatusDetail");

    dashboardElements.toastContainer =
        document.getElementById("toastContainer");

    dashboardElements.viewAllBookingsButton =
        document.getElementById("viewAllBookingsButton");

    dashboardElements.reminderMetricStatus =
        document.getElementById("reminderMetricStatus");

    dashboardElements.vapiConnectionStatus =
        document.getElementById("vapiConnectionStatus");

    dashboardElements.calendarConnectionStatus =
        document.getElementById("calendarConnectionStatus");

    dashboardElements.dvlaConnectionStatus =
        document.getElementById("dvlaConnectionStatus");

    dashboardElements.backendConnectionStatus =
        document.getElementById("backendConnectionStatus");
}


/* =========================================================
   6. START DASHBOARD
   ========================================================= */

document.addEventListener("DOMContentLoaded", initialiseDashboard);

function initialiseDashboard() {
    loadDashboardElements();
    updateHeaderDate();
    bindDashboardEvents();

    const initialData = getInitialDashboardData();

    dashboardState.data = normaliseDashboardData(initialData);
    renderDashboard(dashboardState.data);

    refreshDashboard({
        silent: true
    });
}


/* =========================================================
   7. INITIAL SERVER DATA

   A later Flask route can optionally create:

   window.TRIMTECH_DASHBOARD_DATA = {...};

   The dashboard also works without it.
   ========================================================= */

function getInitialDashboardData() {
    const serverData = window.TRIMTECH_DASHBOARD_DATA;

    if (
        serverData &&
        typeof serverData === "object" &&
        !Array.isArray(serverData)
    ) {
        return serverData;
    }

    return getDefaultDashboardData();
}


/* =========================================================
   8. NORMALISE API DATA
   ========================================================= */

function normaliseDashboardData(rawData) {
    const defaults = getDefaultDashboardData();

    if (
        !rawData ||
        typeof rawData !== "object" ||
        Array.isArray(rawData)
    ) {
        return defaults;
    }

    return {
        summary: {
            ...defaults.summary,
            ...(rawData.summary || {})
        },

        next_appointment:
            rawData.next_appointment ||
            defaults.next_appointment,

        booking_activity:
            Array.isArray(rawData.booking_activity)
                ? rawData.booking_activity
                : defaults.booking_activity,

        service_performance:
            Array.isArray(rawData.service_performance) &&
            rawData.service_performance.length > 0
                ? rawData.service_performance
                : defaults.service_performance,

        upcoming_appointments:
            Array.isArray(rawData.upcoming_appointments)
                ? rawData.upcoming_appointments
                : defaults.upcoming_appointments,

        reminders: {
            ...defaults.reminders,
            ...(rawData.reminders || {})
        },

        ai_activity:
            Array.isArray(rawData.ai_activity)
                ? rawData.ai_activity
                : defaults.ai_activity,

        systems: {
            ...defaults.systems,
            ...(rawData.systems || {})
        }
    };
}


/* =========================================================
   9. EVENT LISTENERS
   ========================================================= */

function bindDashboardEvents() {
    const navigationLinks =
        document.querySelectorAll("[data-navigation-link]");

    navigationLinks.forEach((link) => {
        link.addEventListener("click", () => {
            setActiveNavigationLink(link);
            closeMobileSidebar();
        });
    });

    if (dashboardElements.menuButton) {
        dashboardElements.menuButton.addEventListener(
            "click",
            toggleMobileSidebar
        );
    }

    if (dashboardElements.mobileOverlay) {
        dashboardElements.mobileOverlay.addEventListener(
            "click",
            closeMobileSidebar
        );
    }

    if (dashboardElements.refreshButton) {
        dashboardElements.refreshButton.addEventListener(
            "click",
            () => refreshDashboard()
        );
    }

    if (dashboardElements.runRemindersButton) {
        dashboardElements.runRemindersButton.addEventListener(
            "click",
            runReminders
        );
    }

    if (dashboardElements.viewAllBookingsButton) {
        dashboardElements.viewAllBookingsButton.addEventListener(
            "click",
            () => scrollToSection("bookings")
        );
    }

    document
        .querySelectorAll("[data-quick-action]")
        .forEach((button) => {
            button.addEventListener("click", () => {
                handleQuickAction(
                    button.dataset.quickAction
                );
            });
        });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 980) {
            closeMobileSidebar();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeMobileSidebar();
        }
    });
}


/* =========================================================
   10. SIDEBAR CONTROLS
   ========================================================= */

function toggleMobileSidebar() {
    if (
        !dashboardElements.sidebar ||
        !dashboardElements.mobileOverlay
    ) {
        return;
    }

    const isOpen =
        dashboardElements.sidebar.classList.toggle("open");

    dashboardElements.mobileOverlay.classList.toggle(
        "visible",
        isOpen
    );

    document.body.classList.toggle(
        "sidebar-open",
        isOpen
    );

    dashboardElements.menuButton?.setAttribute(
        "aria-expanded",
        String(isOpen)
    );
}

function closeMobileSidebar() {
    dashboardElements.sidebar?.classList.remove("open");
    dashboardElements.mobileOverlay?.classList.remove("visible");
    document.body.classList.remove("sidebar-open");

    dashboardElements.menuButton?.setAttribute(
        "aria-expanded",
        "false"
    );
}

function setActiveNavigationLink(selectedLink) {
    document
        .querySelectorAll("[data-navigation-link]")
        .forEach((link) => {
            link.classList.remove("active");
        });

    selectedLink.classList.add("active");
}


/* =========================================================
   11. QUICK ACTIONS
   ========================================================= */

function handleQuickAction(action) {
    switch (action) {
        case "refresh":
            refreshDashboard();
            break;

        case "reminders":
            runReminders();
            break;

        case "bookings":
            scrollToSection("bookings");
            break;

        case "customers":
            scrollToSection("customers");
            break;

        default:
            showToast(
                "Action unavailable",
                "This dashboard action has not been connected yet.",
                "info"
            );
    }
}

function scrollToSection(sectionId) {
    const section = document.getElementById(sectionId);

    if (!section) {
        return;
    }

    section.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}


/* =========================================================
   12. HEADER DATE
   ========================================================= */

function updateHeaderDate() {
    if (!dashboardElements.headerDate) {
        return;
    }

    const now = new Date();

    dashboardElements.headerDate.textContent =
        new Intl.DateTimeFormat("en-GB", {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric"
        }).format(now);
}


/* =========================================================
   13. LOAD DASHBOARD DATA
   ========================================================= */

async function refreshDashboard(options = {}) {
    if (dashboardState.loading) {
        return;
    }

    dashboardState.loading = true;
    setButtonLoading(
        dashboardElements.refreshButton,
        true
    );

    try {
        const response = await fetch(API_ENDPOINTS.dashboard, {
            method: "GET",
            headers: {
                Accept: "application/json"
            },
            cache: "no-store"
        });

        if (!response.ok) {
            throw new Error(
                `Dashboard request returned ${response.status}`
            );
        }

        const responseData = await response.json();

        const dashboardData =
            responseData.data ||
            responseData.dashboard ||
            responseData;

        dashboardState.data =
            normaliseDashboardData(dashboardData);

        renderDashboard(dashboardState.data);

        if (!options.silent) {
            showToast(
                "Dashboard updated",
                "The latest garage information has been loaded.",
                "success"
            );
        }
    } catch (error) {
        console.warn(
            "TrimTech dashboard refresh failed:",
            error
        );

        /*
         * The dashboard should not show an error when the backend
         * route has not been created yet during development.
         */
        if (
            !options.silent &&
            !String(error.message).includes("404")
        ) {
            showToast(
                "Unable to refresh",
                "The current dashboard information is still displayed.",
                "error"
            );
        }
    } finally {
        dashboardState.loading = false;

        setButtonLoading(
            dashboardElements.refreshButton,
            false
        );
    }
}


/* =========================================================
   14. RUN REMINDERS
   ========================================================= */

async function runReminders() {
    if (dashboardState.remindersRunning) {
        return;
    }

    dashboardState.remindersRunning = true;

    setButtonLoading(
        dashboardElements.runRemindersButton,
        true
    );

    try {
        const response = await fetch(
            API_ENDPOINTS.runReminders,
            {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    source: "dashboard"
                })
            }
        );

        const result =
            await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(
                result.error ||
                result.message ||
                `Reminder request returned ${response.status}`
            );
        }

        const processed = safeNumber(
            result.processed ??
            result.reminders_processed ??
            result.sent ??
            result.total_processed
        );

        showToast(
            "Reminders processed",
            `${formatNumber(processed)} reminder${
                processed === 1 ? "" : "s"
            } processed successfully.`,
            "success"
        );

        await refreshDashboard({
            silent: true
        });
    } catch (error) {
        console.error(
            "Reminder processing failed:",
            error
        );

        showToast(
            "Reminders not processed",
            error.message ||
                "The reminder service could not be reached.",
            "error"
        );
    } finally {
        dashboardState.remindersRunning = false;

        setButtonLoading(
            dashboardElements.runRemindersButton,
            false
        );
    }
}


/* =========================================================
   15. MAIN RENDER FUNCTION
   ========================================================= */

function renderDashboard(data) {
    renderSummary(data.summary);
    renderNextAppointment(data.next_appointment);
    renderBookingChart(data.booking_activity);
    renderServicePerformance(data.service_performance);
    renderUpcomingAppointments(
        data.upcoming_appointments
    );
    renderReminderHealth(data.reminders);
    renderAIActivity(data.ai_activity);
    renderSystemHealth(data.systems);
}


/* =========================================================
   16. DASHBOARD SUMMARY CARDS
   ========================================================= */

function renderSummary(summary) {
    const todayBookings = safeNumber(
        summary.today_bookings
    );

    const upcomingBookings = safeNumber(
        summary.upcoming_bookings
    );

    const remindersDue = safeNumber(
        summary.reminders_due
    );

    const totalCustomers = safeNumber(
        summary.total_customers
    );

    setText(
        dashboardElements.todayBookings,
        formatNumber(todayBookings)
    );

    setText(
        dashboardElements.upcomingBookings,
        formatNumber(upcomingBookings)
    );

    setText(
        dashboardElements.remindersDue,
        formatNumber(remindersDue)
    );

    setText(
        dashboardElements.revenue,
        formatCurrency(summary.estimated_revenue)
    );

    setText(
        dashboardElements.navigationBookingCount,
        formatNumber(upcomingBookings)
    );

    setText(
        dashboardElements.navigationReminderCount,
        formatNumber(remindersDue)
    );

    setText(
        dashboardElements.totalCustomers,
        `${formatNumber(totalCustomers)} customer${
            totalCustomers === 1 ? "" : "s"
        }`
    );

    if (dashboardElements.reminderMetricStatus) {
        dashboardElements.reminderMetricStatus.textContent =
            remindersDue > 0 ? "Action needed" : "Up to date";

        dashboardElements.reminderMetricStatus.className =
            remindersDue > 0
                ? "metric-change warning"
                : "metric-change positive";
    }
}


/* =========================================================
   17. NEXT APPOINTMENT
   ========================================================= */

function renderNextAppointment(appointment) {
    if (!appointment) {
        setText(
            dashboardElements.nextAppointmentTime,
            "—"
        );

        setText(
            dashboardElements.nextAppointmentDetail,
            "No upcoming booking loaded"
        );

        return;
    }

    const dateValue =
        appointment.start ||
        appointment.datetime ||
        appointment.date_time ||
        appointment.date;

    const appointmentDate = parseDate(dateValue);

    const customer =
        appointment.customer_name ||
        appointment.name ||
        "Customer";

    const service =
        appointment.service ||
        appointment.service_name ||
        "Garage appointment";

    setText(
        dashboardElements.nextAppointmentTime,
        appointmentDate
            ? formatTime(appointmentDate)
            : appointment.time || "Upcoming"
    );

    setText(
        dashboardElements.nextAppointmentDetail,
        `${customer} · ${service}`
    );
}


/* =========================================================
   18. SEVEN-DAY BOOKING CHART
   ========================================================= */

function renderBookingChart(activity) {
    const chartColumns = Array.from(
        document.querySelectorAll(
            "[data-chart-column]"
        )
    );

    const values = buildSevenDayActivity(activity);

    const maximumValue = Math.max(
        1,
        ...values.map((item) => item.value)
    );

    const totalBookings = values.reduce(
        (total, item) => total + item.value,
        0
    );

    setText(
        dashboardElements.chartTotalBookings,
        formatNumber(totalBookings)
    );

    chartColumns.forEach((column, index) => {
        const item = values[index] || {
            label: "",
            value: 0
        };

        const bar =
            column.querySelector(".chart-bar");

        const label =
            column.querySelector(".chart-day");

        if (!bar || !label) {
            return;
        }

        const height =
            item.value === 0
                ? 5
                : Math.max(
                    10,
                    Math.round(
                        (item.value / maximumValue) * 100
                    )
                );

        bar.style.height = `${height}%`;

        bar.dataset.value =
            `${formatNumber(item.value)} booking${
                item.value === 1 ? "" : "s"
            }`;

        label.textContent = item.label;
    });
}

function buildSevenDayActivity(activity) {
    const dayFormatter =
        new Intl.DateTimeFormat("en-GB", {
            weekday: "short"
        });

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const days = [];

    for (let offset = 6; offset >= 0; offset -= 1) {
        const date = new Date(today);
        date.setDate(today.getDate() - offset);

        days.push({
            date,
            key: localDateKey(date),
            label: dayFormatter
                .format(date)
                .replace(".", ""),
            value: 0
        });
    }

    if (!Array.isArray(activity)) {
        return days;
    }

    activity.forEach((item, index) => {
        if (typeof item === "number") {
            if (days[index]) {
                days[index].value = safeNumber(item);
            }

            return;
        }

        if (
            !item ||
            typeof item !== "object"
        ) {
            return;
        }

        const value = safeNumber(
            item.value ??
            item.bookings ??
            item.count
        );

        const itemDate = parseDate(
            item.date ||
            item.day_date ||
            item.datetime
        );

        if (itemDate) {
            const matchingDay = days.find(
                (day) =>
                    day.key === localDateKey(itemDate)
            );

            if (matchingDay) {
                matchingDay.value = value;
            }

            return;
        }

        if (days[index]) {
            days[index].value = value;

            if (item.label || item.day) {
                days[index].label =
                    item.label || item.day;
            }
        }
    });

    return days;
}


/* =========================================================
   19. SERVICE PERFORMANCE
   ========================================================= */

function renderServicePerformance(services) {
    if (!dashboardElements.servicePerformanceList) {
        return;
    }

    if (
        !Array.isArray(services) ||
        services.length === 0
    ) {
        dashboardElements.servicePerformanceList.innerHTML =
            createEmptyState(
                "🔧",
                "No service data",
                "Service booking totals will appear here."
            );

        return;
    }

    const maximumBookings = Math.max(
        1,
        ...services.map((service) =>
            safeNumber(
                service.bookings ??
                service.count ??
                service.value
            )
        )
    );

    dashboardElements.servicePerformanceList.innerHTML =
        services
            .slice(0, 6)
            .map((service) => {
                const name =
                    service.name ||
                    service.service ||
                    "Garage Service";

                const bookings = safeNumber(
                    service.bookings ??
                    service.count ??
                    service.value
                );

                const percentage = Math.round(
                    (bookings / maximumBookings) * 100
                );

                return `
                    <div class="service-row">
                        <div class="service-row-top">
                            <div class="service-name">
                                <span class="service-icon">
                                    ${getServiceIcon(name)}
                                </span>

                                ${escapeHtml(name)}
                            </div>

                            <span class="service-number">
                                ${formatNumber(bookings)}
                                booking${bookings === 1 ? "" : "s"}
                            </span>
                        </div>

                        <div class="service-progress">
                            <div
                                class="service-progress-bar"
                                style="width: ${percentage}%;"
                            ></div>
                        </div>
                    </div>
                `;
            })
            .join("");
}


/* =========================================================
   20. UPCOMING APPOINTMENTS TABLE
   ========================================================= */

function renderUpcomingAppointments(appointments) {
    if (!dashboardElements.bookingsTableBody) {
        return;
    }

    const upcomingAppointments =
        Array.isArray(appointments)
            ? appointments.slice(0, 8)
            : [];

    if (upcomingAppointments.length === 0) {
        dashboardElements.bookingsTableBody.innerHTML = `
            <tr>
                <td colspan="5">
                    ${createEmptyState(
                        "📅",
                        "No upcoming appointments",
                        "New bookings made by the Garage AI will appear here."
                    )}
                </td>
            </tr>
        `;

        return;
    }

    dashboardElements.bookingsTableBody.innerHTML =
        upcomingAppointments
            .map(createAppointmentRow)
            .join("");
}

function createAppointmentRow(appointment) {
    const customer =
        appointment.customer_name ||
        appointment.name ||
        "Customer";

    const phone =
        appointment.phone ||
        appointment.customer_phone ||
        "Phone not recorded";

    const registration =
        appointment.vehicle_reg ||
        appointment.registration ||
        appointment.reg ||
        "—";

    const service =
        appointment.service ||
        appointment.service_name ||
        "Garage appointment";

    const dateValue =
        appointment.start ||
        appointment.datetime ||
        appointment.date_time ||
        appointment.date;

    const parsedDate = parseDate(dateValue);

    const dateText = parsedDate
        ? formatAppointmentDate(parsedDate)
        : appointment.formatted_date ||
          appointment.time ||
          "Date unavailable";

    const status = String(
        appointment.status || "confirmed"
    ).toLowerCase();

    return `
        <tr>
            <td>
                <div class="customer-cell">
                    <div class="customer-avatar">
                        ${getCustomerInitials(customer)}
                    </div>

                    <div>
                        <div class="customer-name">
                            ${escapeHtml(customer)}
                        </div>

                        <div class="customer-phone">
                            ${escapeHtml(phone)}
                        </div>
                    </div>
                </div>
            </td>

            <td>
                <span class="vehicle-registration">
                    ${escapeHtml(
                        String(registration).toUpperCase()
                    )}
                </span>
            </td>

            <td>
                ${escapeHtml(service)}
            </td>

            <td>
                ${escapeHtml(dateText)}
            </td>

            <td>
                <span class="status-badge ${getStatusClass(status)}">
                    ${escapeHtml(capitalise(status))}
                </span>
            </td>
        </tr>
    `;
}


/* =========================================================
   21. REMINDER HEALTH
   ========================================================= */

function renderReminderHealth(reminders) {
    const enabled = reminders.enabled !== false;

    const remindersDue = safeNumber(
        reminders.due ??
        reminders.waiting
    );

    const remindersSent = safeNumber(
        reminders.sent_this_month ??
        reminders.sent
    );

    const status = String(
        reminders.status ||
        (enabled ? "ready" : "disabled")
    ).toLowerCase();

    if (dashboardElements.reminderSystemBadge) {
        dashboardElements.reminderSystemBadge.textContent =
            enabled ? "Active" : "Disabled";

        dashboardElements.reminderSystemBadge.className =
            `status-badge ${
                enabled ? "confirmed" : "cancelled"
            }`;
    }

    setText(
        dashboardElements.schedulerStatus,
        capitalise(status)
    );

    setText(
        dashboardElements.remindersWaiting,
        formatNumber(remindersDue)
    );

    setText(
        dashboardElements.remindersSent,
        formatNumber(remindersSent)
    );

    setText(
        dashboardElements.remindersSentDetail,
        `Successfully processed ${
            reminders.period || "this month"
        }`
    );

    const lastRun = parseDate(reminders.last_run);

    setText(
        dashboardElements.schedulerLastRun,
        lastRun
            ? `Last run ${formatRelativeTime(lastRun)}`
            : "No reminder run recorded yet"
    );
}


/* =========================================================
   22. RECENT AI ACTIVITY
   ========================================================= */

function renderAIActivity(activity) {
    if (!dashboardElements.aiActivityList) {
        return;
    }

    if (
        !Array.isArray(activity) ||
        activity.length === 0
    ) {
        dashboardElements.aiActivityList.innerHTML = `
            <div class="activity-item">
                <div class="activity-icon">🤖</div>

                <div class="activity-copy">
                    <h4>Garage AI is ready</h4>

                    <p>
                        New calls, bookings and customer actions
                        will appear here.
                    </p>

                    <span class="activity-time">
                        Live system
                    </span>
                </div>
            </div>
        `;

        return;
    }

    dashboardElements.aiActivityList.innerHTML =
        activity
            .slice(0, 6)
            .map((item) => {
                const type = String(
                    item.type || "ai"
                ).toLowerCase();

                const title =
                    item.title ||
                    item.action ||
                    "Garage AI activity";

                const detail =
                    item.detail ||
                    item.description ||
                    "";

                const activityDate = parseDate(
                    item.created_at ||
                    item.timestamp ||
                    item.time
                );

                return `
                    <div class="activity-item">
                        <div class="activity-icon">
                            ${getActivityIcon(type)}
                        </div>

                        <div class="activity-copy">
                            <h4>
                                ${escapeHtml(title)}
                            </h4>

                            ${
                                detail
                                    ? `
                                        <p>
                                            ${escapeHtml(detail)}
                                        </p>
                                    `
                                    : ""
                            }

                            <span class="activity-time">
                                ${
                                    activityDate
                                        ? escapeHtml(
                                            formatRelativeTime(
                                                activityDate
                                            )
                                        )
                                        : "Recently"
                                }
                            </span>
                        </div>
                    </div>
                `;
            })
            .join("");
}


/* =========================================================
   23. SYSTEM HEALTH
   ========================================================= */

function renderSystemHealth(systems) {
    const overall = String(
        systems.overall || "operational"
    ).toLowerCase();

    const isOperational = isConnectedStatus(overall);

    if (dashboardElements.overallSystemStatus) {
        dashboardElements.overallSystemStatus.textContent =
            capitalise(overall);

        dashboardElements.overallSystemStatus.className =
            `status-badge ${
                isOperational
                    ? "confirmed"
                    : "pending"
            }`;
    }

    setText(
        dashboardElements.vapiConnectionStatus,
        getConnectionText(
            systems.vapi,
            "Ready for inbound calls"
        )
    );

    setText(
        dashboardElements.calendarConnectionStatus,
        getConnectionText(
            systems.calendar,
            "Booking calendar connected"
        )
    );

    setText(
        dashboardElements.dvlaConnectionStatus,
        getConnectionText(
            systems.dvla,
            "Vehicle lookup available"
        )
    );

    setText(
        dashboardElements.backendConnectionStatus,
        getConnectionText(
            systems.backend,
            "Flask service online"
        )
    );

    setText(
        dashboardElements.sidebarStatusText,
        isOperational
            ? "Garage AI online"
            : "Garage AI needs attention"
    );

    setText(
        dashboardElements.sidebarStatusDetail,
        isOperational
            ? "Voice, calendar and reminder services are operational."
            : "One or more dashboard services reported an issue."
    );
}


/* =========================================================
   24. BUTTON LOADING STATE
   ========================================================= */

function setButtonLoading(button, loading) {
    if (!button) {
        return;
    }

    button.classList.toggle("loading", loading);
    button.disabled = loading;
    button.setAttribute(
        "aria-busy",
        String(loading)
    );
}


/* =========================================================
   25. TOAST NOTIFICATIONS
   ========================================================= */

function showToast(title, message, type = "info") {
    if (!dashboardElements.toastContainer) {
        return;
    }

    const toast = document.createElement("div");

    toast.className = `toast ${type}`;
    toast.setAttribute("role", "status");

    const icon =
        type === "success"
            ? "✓"
            : type === "error"
                ? "!"
                : "i";

    toast.innerHTML = `
        <div class="toast-icon">
            ${icon}
        </div>

        <div class="toast-copy">
            <h4>${escapeHtml(title)}</h4>
            <p>${escapeHtml(message)}</p>
        </div>
    `;

    dashboardElements.toastContainer.appendChild(toast);

    window.setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(10px)";

        window.setTimeout(() => {
            toast.remove();
        }, 250);
    }, 4200);
}


/* =========================================================
   26. DISPLAY HELPERS
   ========================================================= */

function createEmptyState(icon, title, message) {
    return `
        <div class="empty-state">
            <div class="empty-state-icon">
                ${icon}
            </div>

            <h4>${escapeHtml(title)}</h4>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
}

function setText(element, value) {
    if (element) {
        element.textContent = String(value ?? "");
    }
}

function getServiceIcon(serviceName) {
    const normalisedName = String(serviceName)
        .trim()
        .toLowerCase();

    if (SERVICE_ICONS[normalisedName]) {
        return SERVICE_ICONS[normalisedName];
    }

    const matchingService =
        Object.entries(SERVICE_ICONS).find(
            ([serviceKey]) =>
                normalisedName.includes(serviceKey)
        );

    return matchingService
        ? matchingService[1]
        : "🔧";
}

function getActivityIcon(type) {
    return ACTIVITY_ICONS[type] || "🤖";
}

function getStatusClass(status) {
    if (status.includes("cancel")) {
        return "cancelled";
    }

    if (status.includes("complete")) {
        return "completed";
    }

    if (
        status.includes("pending") ||
        status.includes("provisional")
    ) {
        return "pending";
    }

    return "confirmed";
}

function getCustomerInitials(name) {
    const words = String(name)
        .trim()
        .split(/\s+/)
        .filter(Boolean);

    if (words.length === 0) {
        return "CU";
    }

    return words
        .slice(0, 2)
        .map((word) =>
            word.charAt(0).toUpperCase()
        )
        .join("");
}


/* =========================================================
   27. SYSTEM STATUS HELPERS
   ========================================================= */

function isConnectedStatus(status) {
    const normalisedStatus =
        String(status || "").toLowerCase();

    return [
        "operational",
        "online",
        "connected",
        "healthy",
        "ready",
        "active",
        "true"
    ].includes(normalisedStatus);
}

function getConnectionText(value, connectedText) {
    const status = String(
        value || "connected"
    ).toLowerCase();

    if (isConnectedStatus(status)) {
        return connectedText;
    }

    if (
        [
            "disabled",
            "offline",
            "error",
            "disconnected",
            "false"
        ].includes(status)
    ) {
        return `${capitalise(status)} — check configuration`;
    }

    return capitalise(status);
}


/* =========================================================
   28. NUMBER AND CURRENCY HELPERS
   ========================================================= */

function safeNumber(value) {
    const parsedValue = Number(value);

    return Number.isFinite(parsedValue)
        ? parsedValue
        : 0;
}

function formatNumber(value) {
    return new Intl.NumberFormat("en-GB").format(
        safeNumber(value)
    );
}

function formatCurrency(value) {
    const amount = Number(value);

    if (!Number.isFinite(amount)) {
        return "£0";
    }

    return new Intl.NumberFormat("en-GB", {
        style: "currency",
        currency: "GBP",
        maximumFractionDigits:
            Number.isInteger(amount) ? 0 : 2
    }).format(amount);
}


/* =========================================================
   29. DATE AND TIME HELPERS
   ========================================================= */

function parseDate(value) {
    if (!value) {
        return null;
    }

    const date =
        value instanceof Date
            ? value
            : new Date(value);

    return Number.isNaN(date.getTime())
        ? null
        : date;
}

function formatTime(date) {
    return new Intl.DateTimeFormat("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: true
    })
        .format(date)
        .replace("am", "AM")
        .replace("pm", "PM");
}

function formatAppointmentDate(date) {
    return new Intl.DateTimeFormat("en-GB", {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        hour12: true
    })
        .format(date)
        .replace("am", "AM")
        .replace("pm", "PM");
}

function formatRelativeTime(date) {
    const differenceMilliseconds =
        date.getTime() - Date.now();

    const differenceMinutes = Math.round(
        differenceMilliseconds / 60000
    );

    const relativeFormatter =
        new Intl.RelativeTimeFormat("en-GB", {
            numeric: "auto"
        });

    if (Math.abs(differenceMinutes) < 60) {
        return relativeFormatter.format(
            differenceMinutes,
            "minute"
        );
    }

    const differenceHours = Math.round(
        differenceMinutes / 60
    );

    if (Math.abs(differenceHours) < 24) {
        return relativeFormatter.format(
            differenceHours,
            "hour"
        );
    }

    const differenceDays = Math.round(
        differenceHours / 24
    );

    return relativeFormatter.format(
        differenceDays,
        "day"
    );
}

function localDateKey(date) {
    const year = date.getFullYear();

    const month = String(
        date.getMonth() + 1
    ).padStart(2, "0");

    const day = String(
        date.getDate()
    ).padStart(2, "0");

    return `${year}-${month}-${day}`;
}


/* =========================================================
   30. TEXT SAFETY HELPERS
   ========================================================= */

function capitalise(value) {
    const text = String(value || "").trim();

    if (!text) {
        return "";
    }

    return (
        text.charAt(0).toUpperCase() +
        text.slice(1)
    );
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}