"use strict";

/* =========================================================
   TRIMTECH GARAGE AI DASHBOARD
   File: static/dashboard.js
   Version: 1.1-customer-crm
   ========================================================= */

const API_ENDPOINTS = {
    dashboard: "/api/dashboard-data",
    runReminders: "/api/run-reminders"
};

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

function getDefaultDashboardData() {
    return {
        summary: {
            today_bookings: 0,
            upcoming_bookings: 0,
            reminders_due: 0,
            estimated_revenue: 0,
            total_customers: 0,
            today_change: null,
            revenue_period: "Estimated from upcoming work"
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
        customers: [],

        reminders: {
            enabled: true,
            due: 0,
            waiting: 0,
            sent_this_month: 0,
            failed: 0,
            last_run: null,
            status: "ready",
            queue: []
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

const dashboardState = {
    data: getDefaultDashboardData(),
    loading: false,
    remindersRunning: false,
   
    bookingQuery: "",
    bookingService: "",
    bookingStatus: "",
   
    customerQuery: "",
    vehicleQuery: "",

    selectedBooking: null,
    selectedCustomer: null,
    selectedVehicle: null
};

const el = {};

function loadElements() {
    const ids = [
        "dashboardSidebar",
        "mobileOverlay",
        "menuButton",
        "refreshDashboardButton",
        "runRemindersButton",
        "headerDate",
        "todayBookingsMetric",
        "todayBookingsChange",
        "upcomingBookingsMetric",
        "remindersDueMetric",
        "reminderMetricStatus",
        "revenueMetric",
        "revenuePeriod",
        "navigationBookingCount",
        "navigationReminderCount",
        "nextAppointmentTime",
        "nextAppointmentDetail",
        "bookingChartPeriod",
        "chartTotalBookings",
        "servicePerformanceList",
        "upcomingBookingsTableBody",
        "bookingSearchInput",
        "bookingServiceFilter",
        "bookingStatusFilter",
        "clearBookingFiltersButton",
        "reminderSystemBadge",
        "schedulerLastRun",
        "schedulerStatus",
        "remindersWaitingValue",
        "remindersSentValue",
        "remindersSentDetail",
        "aiActivityList",
        "totalCustomersLabel",
        "customerSearchInput",
        "customerDirectory",
        "totalVehiclesLabel",
        "vehicleSearchInput",
        "vehicleDirectory",
        "overallSystemStatus",
        "sidebarStatusPulse",
        "sidebarStatusText",
        "sidebarStatusDetail",
        "vapiConnectionStatus",
        "calendarConnectionStatus",
        "dvlaConnectionStatus",
        "reminderConnectionStatus",
        "backendConnectionStatus",
        "toastContainer",
        "viewAllBookingsButton",
        "drawerOverlay",
        "customerDrawer",
        "customerDrawerTitle",
        "customerDrawerBody",
        "vehicleDrawer",
        "vehicleDrawerTitle",
        "vehicleDrawerBody",
        "reminderDrawer",
        "reminderDrawerTitle",
        "reminderCentreWaiting",
        "reminderCentreSent",
        "reminderCentreFailed",
        "reminderQueueList",
        "bookingDetailsModal",
        "bookingDetailsTitle",
        "closeBookingDetailsButton",
        "bookingDetailsBody"
    ];

    ids.forEach((id) => {
        el[id] = document.getElementById(id);
    });
}

document.addEventListener(
    "DOMContentLoaded",
    initialiseDashboard
);

window.addEventListener(
    "pageshow",
    (event) => {
        if (event.persisted) {
            refreshDashboard({
                silent: true
            });
        }
    }
);

document.addEventListener(
    "visibilitychange",
    () => {
        if (
            document.visibilityState === "visible" &&
            !dashboardState.loading
        ) {
            refreshDashboard({
                silent: true
            });
        }
    }
);

function initialiseDashboard() {
    loadElements();
    updateHeaderDate();
    bindEvents();

    dashboardState.data = normaliseDashboardData(
        window.TRIMTECH_DASHBOARD_DATA || {}
    );

    renderDashboard();

    refreshDashboard({
        silent: true
    });
}

function normaliseDashboardData(raw) {
    const defaults = getDefaultDashboardData();

    const data =
        raw &&
        typeof raw === "object" &&
        !Array.isArray(raw)
            ? raw
            : {};

    return {
        business: {
            ...(data.business || {})
        },

        ui: {
            ...(data.ui || {})
        },

        summary: {
            ...defaults.summary,
            ...(data.summary || {})
        },

        next_appointment:
            data.next_appointment ||
            defaults.next_appointment,

        booking_activity:
            Array.isArray(data.booking_activity)
                ? data.booking_activity
                : [],

        service_performance:
            Array.isArray(data.service_performance) &&
            data.service_performance.length
                ? data.service_performance
                : defaults.service_performance,

        upcoming_appointments:
            Array.isArray(data.upcoming_appointments)
                ? data.upcoming_appointments
                : [],

        booking_history:
            Array.isArray(data.booking_history)
                ? data.booking_history
                : [],

        customers:
            Array.isArray(data.customers)
                ? data.customers
                : [],

        vehicles:
            Array.isArray(data.vehicles)
                ? data.vehicles
                : [],

        customer_summary: {
            ...(data.customer_summary || {})
        },

        revenue: {
            ...(data.revenue || {})
        },

        analytics: {
            ...(data.analytics || {})
        },

        reminders: {
            ...defaults.reminders,
            ...(data.reminders || {}),

            queue:
                Array.isArray(
                    data.reminders?.queue
                )
                    ? data.reminders.queue
                    : []
        },

        ai_activity:
            Array.isArray(data.ai_activity)
                ? data.ai_activity
                : [],

        systems: {
            ...defaults.systems,
            ...(data.systems || {})
        },

        meta: {
            ...(data.meta || {})
        }
    };
}

function bindEvents() {
    document
        .querySelectorAll("[data-navigation-link]")
        .forEach((link) => {
            link.addEventListener("click", () => {
                document
                    .querySelectorAll(
                        "[data-navigation-link]"
                    )
                    .forEach((item) => {
                        item.classList.remove("active");
                    });

                link.classList.add("active");
                closeMobileSidebar();
            });
        });

    el.menuButton?.addEventListener(
        "click",
        toggleMobileSidebar
    );

    el.mobileOverlay?.addEventListener(
        "click",
        closeMobileSidebar
    );

    el.refreshDashboardButton?.addEventListener(
        "click",
        () => refreshDashboard()
    );

    el.runRemindersButton?.addEventListener(
        "click",
        runReminders
    );

    document
    .querySelector(
        'a[href="#reminders"]'
    )
    ?.addEventListener(
        "click",
        (event) => {
            event.preventDefault();
            closeMobileSidebar();
            openReminderDrawer();
        }
    );
    
    el.viewAllBookingsButton?.addEventListener(
        "click",
        () => scrollToSection("bookings")
    );

    document
        .querySelectorAll("[data-quick-action]")
        .forEach((button) => {
            button.addEventListener("click", () => {
                handleQuickAction(
                    button.dataset.quickAction
                );
            });
        });

    document
        .querySelectorAll("[data-dashboard-action]")
        .forEach((button) => {
            button.addEventListener("click", () => {
                handleDashboardAction(
                    button.dataset.dashboardAction
                );
            });
        });

    el.bookingSearchInput?.addEventListener(
        "input",
        (event) => {
            dashboardState.bookingQuery =
                event.target.value
                    .trim()
                    .toLowerCase();

            renderUpcomingAppointments();
        }
    );

    el.bookingServiceFilter?.addEventListener(
        "change",
        (event) => {
            dashboardState.bookingService =
                event.target.value
                    .trim()
                    .toLowerCase();

            renderUpcomingAppointments();
        }
    );

    el.bookingStatusFilter?.addEventListener(
        "change",
        (event) => {
            dashboardState.bookingStatus =
                event.target.value
                    .trim()
                    .toLowerCase();

            renderUpcomingAppointments();
        }
    );

    el.clearBookingFiltersButton?.addEventListener(
        "click",
        clearBookingFilters
    );

    el.customerSearchInput?.addEventListener(
        "input",
        (event) => {
            dashboardState.customerQuery =
                event.target.value
                    .trim()
                    .toLowerCase();

            renderCustomerDirectory();
        }
    );

    el.vehicleSearchInput?.addEventListener(
        "input",
        (event) => {
            dashboardState.vehicleQuery =
                event.target.value
                    .trim()
                    .toLowerCase();

            renderVehicleDirectory();
        }
    );

    document
        .querySelectorAll("[data-close-drawer]")
        .forEach((button) => {
            button.addEventListener(
                "click",
                closeAllDrawers
            );
        });

    el.drawerOverlay?.addEventListener(
        "click",
        closeAllDrawers
    );

    el.closeBookingDetailsButton?.addEventListener(
        "click",
        closeBookingModal
    );

    el.bookingDetailsModal?.addEventListener(
        "click",
        (event) => {
            if (event.target === el.bookingDetailsModal) {
                closeBookingModal();
            }
        }
    );

    document.addEventListener(
        "click",
        handleDelegatedClick
    );

    document.addEventListener(
        "keydown",
        (event) => {
            if (event.key === "Escape") {
                closeMobileSidebar();
                closeAllDrawers();
                closeBookingModal();
                closeRevenueCentre();
            }
        }
    );

    window.addEventListener("resize", () => {
        if (window.innerWidth > 980) {
            closeMobileSidebar();
        }
    });
}

function handleDelegatedClick(event) {
    /*
     * Customer and vehicle buttons sit inside booking rows.
     * They must be checked before the booking row itself.
     */

    const customerButton =
        event.target.closest(
            "[data-customer-key]"
        );

    if (customerButton) {
        event.preventDefault();
        event.stopPropagation();

        const wantedKey =
            customerButton.dataset.customerKey;

        const customer =
            getCustomerRecords().find(
                (item) =>
                    customerKey(item) ===
                    wantedKey
            );

        if (customer) {
            openCustomerDrawer(customer);
        }

        return;
    }

    const vehicleButton =
        event.target.closest(
            "[data-vehicle-reg]"
        );

    if (vehicleButton) {
        event.preventDefault();
        event.stopPropagation();

        const vehicle =
            findVehicle(
                vehicleButton.dataset.vehicleReg
            );

        if (vehicle) {
            openVehicleDrawer(vehicle);
        }

        return;
    }

    const bookingButton =
        event.target.closest(
            "[data-booking-index]"
        );

    if (bookingButton) {
        const booking =
            filteredBookings()[
                Number(
                    bookingButton.dataset
                        .bookingIndex
                )
            ];

        if (booking) {
            openBookingModal(booking);
        }
    }
}

function toggleMobileSidebar() {
    const open =
        el.dashboardSidebar?.classList.toggle("open") ||
        false;

    el.mobileOverlay?.classList.toggle(
        "visible",
        open
    );

    document.body.classList.toggle(
        "sidebar-open",
        open
    );

    el.menuButton?.setAttribute(
        "aria-expanded",
        String(open)
    );
}

function closeMobileSidebar() {
    el.dashboardSidebar?.classList.remove("open");
    el.mobileOverlay?.classList.remove("visible");
    document.body.classList.remove("sidebar-open");

    el.menuButton?.setAttribute(
        "aria-expanded",
        "false"
    );
}

function handleQuickAction(action) {
    if (action === "refresh") {
        return refreshDashboard();
    }

    if (action === "reminders") {
        return runReminders();
    }

    if (action === "bookings") {
        return scrollToSection("bookings");
    }

    if (action === "customers") {
        return scrollToSection("customers");
    }
}

function handleDashboardAction(action) {
    if (action === "reminder-centre") {
        return openReminderDrawer();
    }

    if (action === "today-bookings") {
        dashboardState.bookingQuery =
            localDateKey(new Date());

        if (el.bookingSearchInput) {
            el.bookingSearchInput.value =
                dashboardState.bookingQuery;
        }

        scrollToSection("bookings");
        return renderUpcomingAppointments();
    }

        if (action === "upcoming-bookings") {
        return scrollToSection("bookings");
    }

   if (action === "revenue-report") {
    return openRevenueCentre();
   }
}

function scrollToSection(id) {
    document
        .getElementById(id)
        ?.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });
}

function clearBookingFilters() {
    dashboardState.bookingQuery = "";
    dashboardState.bookingService = "";
    dashboardState.bookingStatus = "";

    if (el.bookingSearchInput) {
        el.bookingSearchInput.value = "";
    }

    if (el.bookingServiceFilter) {
        el.bookingServiceFilter.value = "";
    }

    if (el.bookingStatusFilter) {
        el.bookingStatusFilter.value = "";
    }

    renderUpcomingAppointments();
}

function updateHeaderDate() {
    setText(
        el.headerDate,
        new Intl.DateTimeFormat("en-GB", {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric"
        }).format(new Date())
    );
}

async function refreshDashboard(options = {}) {
    if (dashboardState.loading) {
        return;
    }

    dashboardState.loading = true;

    setButtonLoading(
        el.refreshDashboardButton,
        true
    );

    try {
        const response = await fetch(
            API_ENDPOINTS.dashboard,
            {
                headers: {
                    Accept: "application/json"
                },
                cache: "no-store"
            }
        );

        if (!response.ok) {
            throw new Error(
                `Dashboard request returned ${response.status}`
            );
        }

        const json = await response.json();

        dashboardState.data =
            normaliseDashboardData(
                json.data ||
                json.dashboard ||
                json
            );

        renderDashboard();

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
            el.refreshDashboardButton,
            false
        );
    }
}

async function runReminders() {
    if (dashboardState.remindersRunning) {
        return;
    }

    dashboardState.remindersRunning = true;

    setButtonLoading(
        el.runRemindersButton,
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
            await response
                .json()
                .catch(() => ({}));

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
        showToast(
            "Reminders not processed",
            error.message ||
                "The reminder service could not be reached.",
            "error"
        );
    } finally {
        dashboardState.remindersRunning = false;

        setButtonLoading(
            el.runRemindersButton,
            false
        );
    }
}

function renderDashboard() {
    renderSummary();
    renderNextAppointment();
    renderBookingChart();
    renderServicePerformance();
    renderUpcomingAppointments();
    renderReminderHealth();
    renderAIActivity();
    renderCustomerDirectory();
    renderVehicleDirectory();
    renderSystemHealth();
}

function renderSummary() {
    const summary =
        dashboardState.data.summary;

    const today = safeNumber(
        summary.today_bookings
    );

    const upcoming = safeNumber(
        summary.upcoming_bookings
    );

    const remindersDue = safeNumber(
        summary.reminders_due ??
        dashboardState.data.reminders.due
    );

    const customerTotal = safeNumber(
        summary.total_customers ||
        getCustomerRecords().length
    );

    setText(
        el.todayBookingsMetric,
        formatNumber(today)
    );

    setText(
        el.upcomingBookingsMetric,
        formatNumber(upcoming)
    );

    setText(
        el.remindersDueMetric,
        formatNumber(remindersDue)
    );

    setText(
        el.revenueMetric,
        formatCurrency(
            summary.estimated_revenue
        )
    );

    setText(
        el.navigationBookingCount,
        formatNumber(upcoming)
    );

    setText(
        el.navigationReminderCount,
        formatNumber(remindersDue)
    );

    setText(
        el.totalCustomersLabel,
        `${formatNumber(customerTotal)} customer${
            customerTotal === 1 ? "" : "s"
        }`
    );

    setText(
        el.revenuePeriod,
        summary.revenue_period ||
        "Estimated from upcoming work"
    );

    if (el.todayBookingsChange) {
        const change =
            summary.today_change;

        el.todayBookingsChange.textContent =
            change == null
                ? "Live total"
                : `${
                    safeNumber(change) >= 0
                        ? "+"
                        : ""
                }${safeNumber(change)}%`;

        el.todayBookingsChange.className =
            `metric-change ${
                safeNumber(change) < 0
                    ? "negative"
                    : "positive"
            }`;
    }

    if (el.reminderMetricStatus) {
        el.reminderMetricStatus.textContent =
            remindersDue > 0
                ? "Action needed"
                : "Up to date";

        el.reminderMetricStatus.className =
            `metric-change ${
                remindersDue > 0
                    ? "warning"
                    : "positive"
            }`;
    }
}

function renderNextAppointment() {
    const appointment =
        dashboardState.data.next_appointment ||
        dashboardState.data
            .upcoming_appointments[0];

    if (!appointment) {
        setText(
            el.nextAppointmentTime,
            "—"
        );

        setText(
            el.nextAppointmentDetail,
            "No upcoming booking loaded"
        );

        return;
    }

    const date = parseDate(
        bookingDateValue(appointment)
    );

    setText(
        el.nextAppointmentTime,
        date
            ? formatTime(date)
            : appointment.time ||
              "Upcoming"
    );

    setText(
        el.nextAppointmentDetail,
        `${bookingCustomer(appointment)} · ${
            bookingService(appointment)
        }`
    );
}

function renderBookingChart() {
    const columns = Array.from(
        document.querySelectorAll(
            "[data-chart-column]"
        )
    );

    const values =
        buildSevenDayActivity(
            dashboardState.data
                .booking_activity
        );

    const maximumValue = Math.max(
        1,
        ...values.map(
            (item) => item.value
        )
    );

    const total = values.reduce(
        (sum, item) =>
            sum + item.value,
        0
    );

    setText(
        el.chartTotalBookings,
        formatNumber(total)
    );

    setText(
        el.bookingChartPeriod,
        "Last 7 days"
    );

    columns.forEach(
        (column, index) => {
            const item =
                values[index] || {
                    label: "",
                    value: 0
                };

            const bar =
                column.querySelector(
                    ".chart-bar"
                );

            const label =
                column.querySelector(
                    ".chart-day"
                );

            if (!bar || !label) {
                return;
            }

            const height =
                item.value
                    ? Math.max(
                        10,
                        Math.round(
                            (
                                item.value /
                                maximumValue
                            ) * 100
                        )
                    )
                    : 5;

            bar.style.height =
                `${height}%`;

            bar.dataset.value =
                `${formatNumber(
                    item.value
                )} booking${
                    item.value === 1
                        ? ""
                        : "s"
                }`;

            label.textContent =
                item.label;
        }
    );
}

function buildSevenDayActivity(activity) {
    const formatter =
        new Intl.DateTimeFormat(
            "en-GB",
            {
                weekday: "short"
            }
        );

    const today = new Date();

    today.setHours(
        0,
        0,
        0,
        0
    );

    const days = [];

    for (
        let offset = 6;
        offset >= 0;
        offset -= 1
    ) {
        const date =
            new Date(today);

        date.setDate(
            today.getDate() -
            offset
        );

        days.push({
            key: localDateKey(date),
            label: formatter
                .format(date)
                .replace(".", ""),
            value: 0
        });
    }

    const items =
        Array.isArray(activity)
            ? activity
            : [];

    items.forEach(
        (item, index) => {
            if (
                typeof item ===
                "number"
            ) {
                if (days[index]) {
                    days[index].value =
                        safeNumber(item);
                }

                return;
            }

            if (
                !item ||
                typeof item !==
                "object"
            ) {
                return;
            }

            const value =
                safeNumber(
                    item.value ??
                    item.bookings ??
                    item.count
                );

            const date = parseDate(
                item.date ||
                item.day_date ||
                item.datetime
            );

            const match =
                date
                    ? days.find(
                        (day) =>
                            day.key ===
                            localDateKey(
                                date
                            )
                    )
                    : days[index];

            if (match) {
                match.value = value;

                if (
                    item.label ||
                    item.day
                ) {
                    match.label =
                        item.label ||
                        item.day;
                }
            }
        }
    );

    return days;
}

function renderServicePerformance() {
    if (!el.servicePerformanceList) {
        return;
    }

    const services =
        dashboardState.data
            .service_performance;

    if (!services.length) {
        el.servicePerformanceList.innerHTML =
            createEmptyState(
                "🔧",
                "No service data",
                "Service booking totals will appear here."
            );

        return;
    }

    const maximumBookings = Math.max(
        1,
        ...services.map(
            (service) =>
                safeNumber(
                    service.bookings ??
                    service.count ??
                    service.value
                )
        )
    );

    el.servicePerformanceList.innerHTML =
        services
            .slice(0, 6)
            .map((service) => {
                const name =
                    service.name ||
                    service.service ||
                    "Garage Service";

                const bookings =
                    safeNumber(
                        service.bookings ??
                        service.count ??
                        service.value
                    );

                const percentage =
                    Math.round(
                        (
                            bookings /
                            maximumBookings
                        ) * 100
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
                                booking${
                                    bookings === 1
                                        ? ""
                                        : "s"
                                }
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

function filteredBookings() {
    return dashboardState.data
        .upcoming_appointments
        .filter((booking) => {
            const bookingDate =
                parseDate(
                    bookingDateValue(
                        booking
                    )
                );

            const haystack = [
                bookingCustomer(booking),
                bookingPhone(booking),
                bookingRegistration(booking),
                bookingService(booking),
                bookingStatus(booking),
                localDateKey(bookingDate)
            ]
                .join(" ")
                .toLowerCase();

            const queryMatch =
                !dashboardState.bookingQuery ||
                haystack.includes(
                    dashboardState.bookingQuery
                );

            const serviceMatch =
                !dashboardState.bookingService ||
                bookingService(booking)
                    .toLowerCase()
                    .includes(
                        dashboardState.bookingService
                    );

            const statusMatch =
                !dashboardState.bookingStatus ||
                bookingStatus(booking)
                    .includes(
                        dashboardState.bookingStatus
                    );

            return (
                queryMatch &&
                serviceMatch &&
                statusMatch
            );
        });
}

function renderUpcomingAppointments() {
    if (!el.upcomingBookingsTableBody) {
        return;
    }

    const bookings =
        filteredBookings();

    if (!bookings.length) {
        el.upcomingBookingsTableBody.innerHTML = `
            <tr>
                <td colspan="5">
                    ${createEmptyState(
                        "📅",
                        "No matching appointments",
                        "Try clearing your search or filters."
                    )}
                </td>
            </tr>
        `;

        return;
    }

    el.upcomingBookingsTableBody.innerHTML =
        bookings
            .map((booking, index) => {
                const customer =
                    bookingCustomer(
                        booking
                    );

                const phone =
                    bookingPhone(
                        booking
                    );

                const registration =
                    bookingRegistration(
                        booking
                    );

                const service =
                    bookingService(
                        booking
                    );

                const status =
                    bookingStatus(
                        booking
                    );

                const date =
                    parseDate(
                        bookingDateValue(
                            booking
                        )
                    );

                const dateText =
                    date
                        ? formatAppointmentDate(
                            date
                        )
                        : booking.formatted_date ||
                          booking.time ||
                          "Date unavailable";

                const key =
                    customerKey({
                        name: customer,
                        phone
                    });

                return `
                    <tr
                        class="booking-row"
                        data-booking-index="${index}"
                    >
                        <td>
                            <button
                                class="table-link customer-cell"
                                type="button"
                                data-customer-key="${escapeAttribute(
                                    key
                                )}"
                            >
                                <span class="customer-avatar">
                                    ${getCustomerInitials(
                                        customer
                                    )}
                                </span>

                                <span>
                                    <span class="customer-name">
                                        ${escapeHtml(
                                            customer
                                        )}
                                    </span>

                                    <span class="customer-phone">
                                        ${escapeHtml(
                                            phone
                                        )}
                                    </span>
                                </span>
                            </button>
                        </td>

                        <td>
                            <button
                                class="table-link"
                                type="button"
                                data-vehicle-reg="${escapeAttribute(
                                    registration
                                )}"
                            >
                                <span class="vehicle-registration">
                                    ${escapeHtml(
                                        registration.toUpperCase()
                                    )}
                                </span>
                            </button>
                        </td>

                        <td>
                            <button
                                class="table-link booking-detail-link"
                                type="button"
                                data-booking-index="${index}"
                            >
                                ${escapeHtml(service)}
                            </button>
                        </td>

                        <td>
                            <button
                                class="table-link booking-detail-link"
                                type="button"
                                data-booking-index="${index}"
                            >
                                ${escapeHtml(dateText)}
                            </button>
                        </td>

                        <td>
                            <button
                                class="table-link"
                                type="button"
                                data-booking-index="${index}"
                            >
                                <span class="status-badge ${getStatusClass(
                                    status
                                )}">
                                    ${escapeHtml(
                                        capitalise(status)
                                    )}
                                </span>
                            </button>
                        </td>
                    </tr>
                `;
            })
            .join("");
}

function renderReminderHealth() {
    const reminders =
        dashboardState.data.reminders || {};

    const enabled =
        reminders.enabled !== false;

    const due =
        safeNumber(
            reminders.due
        );

    const waiting =
        safeNumber(
            reminders.waiting ??
            reminders.pending ??
            due
        );

    const sent =
        safeNumber(
            reminders.sent_this_month ??
            reminders.sent
        );

    const failed =
        safeNumber(
            reminders.failed
        );

    const status =
        String(
            reminders.status ||
            (
                enabled
                    ? "ready"
                    : "disabled"
            )
        ).toLowerCase();

    const hasError =
        status === "error" ||
        status === "failed" ||
        failed > 0;

    const needsAttention =
        enabled &&
        (
            due > 0 ||
            waiting > 0 ||
            hasError
        );

    if (el.reminderSystemBadge) {
        el.reminderSystemBadge.textContent =
            !enabled
                ? "Disabled"
                : hasError
                    ? "Attention"
                    : "Active";

        el.reminderSystemBadge.className =
            `status-badge ${
                !enabled
                    ? "cancelled"
                    : hasError
                        ? "pending"
                        : "confirmed"
            }`;
    }

    setText(
        el.schedulerStatus,
        !enabled
            ? "Disabled"
            : hasError
                ? "Needs attention"
                : status === "ready"
                    ? "Ready"
                    : capitalise(status)
    );

    setText(
        el.remindersWaitingValue,
        formatNumber(waiting)
    );

    setText(
        el.remindersSentValue,
        formatNumber(sent)
    );

    setText(
        el.remindersSentDetail,
        failed > 0
            ? `${formatNumber(
                failed
            )} failed reminder${
                failed === 1
                    ? ""
                    : "s"
            } need attention`
            : `Successfully processed ${
                reminders.period ||
                "this month"
            }`
    );

    const lastRun =
        parseDate(
            reminders.last_run
        );

    setText(
        el.schedulerLastRun,
        lastRun
            ? `Last run ${formatRelativeTime(
                lastRun
            )}`
            : enabled
                ? "No reminder run recorded yet"
                : "Reminder scheduler is disabled"
    );

    setText(
        el.remindersDueMetric,
        formatNumber(due)
    );

    setText(
        el.navigationReminderCount,
        formatNumber(due)
    );

    if (el.reminderMetricStatus) {
        el.reminderMetricStatus.textContent =
            !enabled
                ? "Disabled"
                : hasError
                    ? "Check failures"
                    : due > 0
                        ? "Action needed"
                        : waiting > 0
                            ? "Scheduled"
                            : "Up to date";

        el.reminderMetricStatus.className =
            `metric-change ${
                !enabled || hasError
                    ? "negative"
                    : needsAttention
                        ? "warning"
                        : "positive"
            }`;
    }
}

function renderAIActivity() {
    if (!el.aiActivityList) {
        return;
    }

    const activity =
        dashboardState.data.ai_activity;

    if (!activity.length) {
        el.aiActivityList.innerHTML = `
            <div class="activity-item">
                <div class="activity-icon">
                    🤖
                </div>

                <div class="activity-copy">
                    <h4>
                        Garage AI is ready
                    </h4>

                    <p>
                        New calls, bookings and customer
                        actions will appear here.
                    </p>

                    <span class="activity-time">
                        Live system
                    </span>
                </div>
            </div>
        `;

        return;
    }

    el.aiActivityList.innerHTML =
        activity
            .slice(0, 6)
            .map((item) => {
                const type =
                    String(
                        item.type ||
                        "ai"
                    ).toLowerCase();

                const title =
                    item.title ||
                    item.action ||
                    "Garage AI activity";

                const detail =
                    item.detail ||
                    item.description ||
                    "";

                const date =
                    parseDate(
                        item.created_at ||
                        item.timestamp ||
                        item.time
                    );

                return `
                    <div class="activity-item">
                        <div class="activity-icon">
                            ${getActivityIcon(
                                type
                            )}
                        </div>

                        <div class="activity-copy">
                            <h4>
                                ${escapeHtml(
                                    title
                                )}
                            </h4>

                            ${
                                detail
                                    ? `
                                        <p>
                                            ${escapeHtml(
                                                detail
                                            )}
                                        </p>
                                    `
                                    : ""
                            }

                            <span class="activity-time">
                                ${
                                    date
                                        ? escapeHtml(
                                            formatRelativeTime(
                                                date
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

function getCustomerRecords() {
    const apiCustomers =
        Array.isArray(
            dashboardState.data.customers
        )
            ? dashboardState.data.customers
            : [];

    if (apiCustomers.length) {
        return apiCustomers.map(
            (customer) => {
                const bookings =
                    Array.isArray(
                        customer.bookings
                    )
                        ? customer.bookings
                        : Array.isArray(
                            customer.booking_history
                        )
                            ? customer.booking_history
                            : Array.isArray(
                                customer.appointments
                            )
                                ? customer.appointments
                                : Array.isArray(
                                    customer.service_history
                                )
                                    ? customer.service_history
                                    : [];

                const vehicles =
                    Array.isArray(
                        customer.vehicles
                    )
                        ? customer.vehicles
                        : Array.isArray(
                            customer.vehicle_profiles
                        )
                            ? customer.vehicle_profiles
                            : [];

                return {
                    ...customer,

                    name:
                        customer.name ||
                        customer.customer_name ||
                        "Customer",

                    customer_name:
                        customer.customer_name ||
                        customer.name ||
                        "Customer",

                    phone:
                        customer.phone ||
                        customer.customer_phone ||
                        "",

                    customer_phone:
                        customer.customer_phone ||
                        customer.phone ||
                        "",

                    email:
                        customer.email ||
                        customer.customer_email ||
                        "",

                    bookings,

                    booking_history:
                        bookings,

                    vehicles,

                    booking_count:
                        safeNumber(
                            customer.booking_count ??
                            customer.total_bookings ??
                            bookings.length
                        ),

                    completed_visit_count:
                        safeNumber(
                            customer.completed_visit_count ??
                            customer.completed_bookings
                        ),

                    upcoming_booking_count:
                        safeNumber(
                            customer.upcoming_booking_count ??
                            customer.upcoming_bookings
                        ),

                    cancelled_booking_count:
                        safeNumber(
                            customer.cancelled_booking_count ??
                            customer.cancelled_bookings
                        ),

                    total_revenue:
                        safeNumber(
                            customer.total_revenue ??
                            customer.lifetime_value ??
                            customer.total_spent
                        )
                };
            }
        );
    }

    const customerMap =
        new Map();

    dashboardState.data
        .upcoming_appointments
        .forEach((booking) => {
            const customer = {
                name:
                    bookingCustomer(
                        booking
                    ),

                customer_name:
                    bookingCustomer(
                        booking
                    ),

                phone:
                    bookingPhone(
                        booking
                    ),

                customer_phone:
                    bookingPhone(
                        booking
                    ),

                email:
                    booking.email ||
                    booking.customer_email ||
                    "",

                vehicles: [],
                bookings: [],
                booking_history: []
            };

            const key =
                customerKey(
                    customer
                );

            const current =
                customerMap.get(key) ||
                customer;

            current.bookings.push(
                booking
            );

            current.booking_history =
                current.bookings;

            const registration =
                bookingRegistration(
                    booking
                );

            const vehicleExists =
                current.vehicles.some(
                    (vehicle) =>
                        bookingRegistration(
                            vehicle
                        ) ===
                        registration
                );

            if (
                registration !== "—" &&
                !vehicleExists
            ) {
                current.vehicles.push({
                    ...booking,
                    registration,
                    vehicle_reg:
                        registration
                });
            }

            current.booking_count =
                current.bookings.length;

            customerMap.set(
                key,
                current
            );
        });

    return Array.from(
        customerMap.values()
    );
}

function renderCustomerDirectory() {
    if (!el.customerDirectory) {
        return;
    }

    const query =
        dashboardState.customerQuery;

    const customers =
        getCustomerRecords()
            .filter((customer) => {
                const vehicles =
                    Array.isArray(
                        customer.vehicles
                    )
                        ? customer.vehicles
                        : [];

                const vehicleRegistrations =
                    vehicles.map(
                        bookingRegistration
                    );

                const haystack = [
                    customer.name,
                    customer.customer_name,
                    customer.phone,
                    customer.customer_phone,
                    customer.email,
                    customer.customer_email,
                    ...vehicleRegistrations
                ]
                    .filter(Boolean)
                    .join(" ")
                    .toLowerCase();

                return (
                    !query ||
                    haystack.includes(query)
                );
            })
            .sort((first, second) => {
                const firstDate =
                    parseDate(
                        first.last_booking_date ||
                        first.last_visit ||
                        first.updated_at
                    );

                const secondDate =
                    parseDate(
                        second.last_booking_date ||
                        second.last_visit ||
                        second.updated_at
                    );

                return (
                    (secondDate?.getTime() || 0) -
                    (firstDate?.getTime() || 0)
                );
            });

    if (!customers.length) {
        el.customerDirectory.innerHTML =
            createEmptyState(
                "👥",
                "No customers found",
                query
                    ? "Try a different customer, phone number or vehicle registration."
                    : "Customer profiles will appear after bookings are loaded.",
                true
            );

        return;
    }

    el.customerDirectory.innerHTML =
        customers
            .slice(0, 18)
            .map((customer) => {
                const name =
                    customer.name ||
                    customer.customer_name ||
                    "Customer";

                const phone =
                    customer.phone ||
                    customer.customer_phone ||
                    "Phone not recorded";

                const vehicles =
                    Array.isArray(
                        customer.vehicles
                    )
                        ? customer.vehicles
                        : [];

                const bookings =
                    Array.isArray(
                        customer.bookings
                    )
                        ? customer.bookings
                        : [];

                const bookingCount =
                    safeNumber(
                        customer.booking_count ??
                        customer.total_bookings ??
                        bookings.length
                    );

                const completedCount =
                    safeNumber(
                        customer.completed_visit_count ??
                        customer.completed_bookings
                    );

                const upcomingCount =
                    safeNumber(
                        customer.upcoming_booking_count ??
                        customer.upcoming_bookings
                    );

                const totalRevenue =
                    safeNumber(
                        customer.total_revenue ??
                        customer.lifetime_value ??
                        customer.total_spent
                    );

                const key =
                    customerKey(customer);

                return `
                    <button
                        class="customer-directory-card"
                        type="button"
                        data-customer-key="${escapeAttribute(
                            key
                        )}"
                        aria-label="Open ${escapeAttribute(
                            name
                        )} customer profile"
                    >
                        <span class="customer-directory-avatar">
                            ${getCustomerInitials(
                                name
                            )}
                        </span>

                        <span class="customer-directory-copy">
                            <strong>
                                ${escapeHtml(name)}
                            </strong>

                            <small>
                                ${escapeHtml(phone)}
                            </small>

                            <span>
                                ${formatNumber(
                                    vehicles.length
                                )}
                                vehicle${
                                    vehicles.length === 1
                                        ? ""
                                        : "s"
                                }
                                ·
                                ${formatNumber(
                                    bookingCount
                                )}
                                booking${
                                    bookingCount === 1
                                        ? ""
                                        : "s"
                                }
                            </span>

                            <span>
                                ${formatNumber(
                                    completedCount
                                )}
                                completed
                                ·
                                ${formatNumber(
                                    upcomingCount
                                )}
                                upcoming
                            </span>

                            <span>
                                Lifetime value:
                                ${formatCurrency(
                                    totalRevenue
                                )}
                            </span>
                        </span>

                        <span class="customer-directory-arrow">
                            ›
                        </span>
                    </button>
                `;
            })
            .join("");
}

function renderVehicleDirectory() {
    if (!el.vehicleDirectory) {
        return;
    }

    const query =
        dashboardState.vehicleQuery;

    const groupedVehicles = new Map();

(
    Array.isArray(
        dashboardState.data.vehicles
    )
        ? dashboardState.data.vehicles
        : []
).forEach((vehicle) => {
    const key = String(
        bookingRegistration(vehicle)
    )
        .replace(/[^A-Z0-9]/gi, "")
        .toUpperCase();

    if (!key) {
        return;
    }

    if (!groupedVehicles.has(key)) {
        groupedVehicles.set(key, {
            ...vehicle,
            booking_count:
                safeNumber(
                    vehicle.booking_count
                ),
            upcoming_booking_count:
                safeNumber(
                    vehicle.upcoming_booking_count
                ),
            total_revenue:
                safeNumber(
                    vehicle.total_revenue
                )
        });

        return;
    }

    const existing =
        groupedVehicles.get(key);

    existing.booking_count +=
        safeNumber(
            vehicle.booking_count
        );

    existing.upcoming_booking_count +=
        safeNumber(
            vehicle.upcoming_booking_count
        );

    existing.total_revenue +=
        safeNumber(
            vehicle.total_revenue
        );

    existing.booking_history = [
        ...(existing.booking_history || []),
        ...(vehicle.booking_history || [])
    ];
});

const vehicles =
    Array.from(
        groupedVehicles.values()
    ).filter((vehicle) => {
                const registration =
                    bookingRegistration(
                        vehicle
                    );

                const owner =
                    vehicle.customer_name ||
                    vehicle.owner_name ||
                    vehicle.name ||
                    "";

                const make =
                    vehicle.make ||
                    vehicle.vehicle_make ||
                    "";

                const model =
                    vehicle.model ||
                    vehicle.vehicle_model ||
                    "";

                const haystack = [
                    registration,
                    owner,
                    make,
                    model,
                    vehicle.colour,
                    vehicle.color,
                    vehicle.fuel_type
                ]
                    .filter(Boolean)
                    .join(" ")
                    .toLowerCase();

                return (
                    !query ||
                    haystack.includes(query)
                );
            })
            .sort((first, second) => {
                const firstDate =
                    parseDate(
                        first.last_visit ||
                        first.last_booking_date ||
                        first.next_booking
                    );

                const secondDate =
                    parseDate(
                        second.last_visit ||
                        second.last_booking_date ||
                        second.next_booking
                    );

                return (
                    (secondDate?.getTime() || 0) -
                    (firstDate?.getTime() || 0)
                );
            });

    setText(
        el.totalVehiclesLabel,
        `${formatNumber(
            vehicles.length
        )} vehicle${
            vehicles.length === 1
                ? ""
                : "s"
        }`
    );

    if (!vehicles.length) {
        el.vehicleDirectory.innerHTML =
            createEmptyState(
                "🚗",
                "No vehicles found",
                query
                    ? "Try another registration, owner, make or model."
                    : "Vehicle profiles will appear when registrations are recorded.",
                true
            );

        return;
    }

    el.vehicleDirectory.innerHTML =
        vehicles
            .slice(0, 24)
            .map((vehicle) => {
                const registration =
                    bookingRegistration(
                        vehicle
                    );

                const owner =
                    vehicle.customer_name ||
                    vehicle.owner_name ||
                    vehicle.name ||
                    "Customer";

                const make =
                    vehicle.make ||
                    vehicle.vehicle_make ||
                    "";

                const model =
                    vehicle.model ||
                    vehicle.vehicle_model ||
                    "";

                const vehicleName =
                    [make, model]
                        .filter(Boolean)
                        .join(" ") ||
                    "Vehicle details unavailable";

                const visits =
                    safeNumber(
                        vehicle.booking_count ??
                        vehicle.total_bookings ??
                        vehicle.visit_count
                    );

                const upcoming =
                    safeNumber(
                        vehicle.upcoming_booking_count ??
                        vehicle.upcoming_bookings
                    );

                const totalRevenue =
                    safeNumber(
                        vehicle.total_revenue ??
                        vehicle.total_spent ??
                        vehicle.lifetime_value
                    );

                const motStatus =
                    vehicle.mot_status ||
                    vehicle.motStatus ||
                    "MOT not loaded";

                return `
                    <button
                        class="vehicle-directory-card"
                        type="button"
                        data-vehicle-reg="${escapeAttribute(
                            registration
                        )}"
                        aria-label="Open vehicle profile for ${escapeAttribute(
                            registration
                        )}"
                    >
                        <span class="vehicle-directory-icon">
                            🚗
                        </span>

                        <span class="vehicle-directory-copy">
                            <strong class="vehicle-directory-registration">
                                ${escapeHtml(
                                    registration
                                )}
                            </strong>

                            <span>
                                ${escapeHtml(
                                    vehicleName
                                )}
                            </span>

                            <small>
                                ${escapeHtml(
                                    owner
                                )}
                            </small>

                            <small>
                                ${formatNumber(
                                    visits
                                )}
                                visit${
                                    visits === 1
                                        ? ""
                                        : "s"
                                }
                                ·
                                ${formatNumber(
                                    upcoming
                                )}
                                upcoming
                            </small>

                            <small>
                                ${escapeHtml(
                                    motStatus
                                )}
                                ·
                                ${escapeHtml(
                                    formatCurrency(
                                        totalRevenue
                                    )
                                )}
                                total
                            </small>
                        </span>

                        <span class="vehicle-directory-arrow">
                            ›
                        </span>
                    </button>
                `;
            })
            .join("");
}

function renderSystemHealth() {
    const systems =
        dashboardState.data.systems || {};

    const reminders =
        dashboardState.data.reminders || {};

    const systemStatuses = {
        vapi:
            systems.vapi ||
            "unknown",

        calendar:
            systems.calendar ||
            "unknown",

        dvla:
            systems.dvla ||
            "unknown",

        reminders:
            systems.reminders ||
            reminders.status ||
            (
                reminders.enabled === false
                    ? "disabled"
                    : "ready"
            ),

        backend:
            systems.backend ||
            "connected"
    };

    const statusValues =
        Object.values(
            systemStatuses
        ).map(
            (status) =>
                String(
                    status || "unknown"
                ).toLowerCase()
        );

    const errorStatuses = [
        "error",
        "failed",
        "offline",
        "disconnected",
        "unavailable"
    ];

    const warningStatuses = [
        "attention",
        "warning",
        "not configured",
        "unknown",
        "disabled"
    ];

    const hasError =
        statusValues.some(
            (status) =>
                errorStatuses.includes(
                    status
                )
        );

    const hasWarning =
        statusValues.some(
            (status) =>
                warningStatuses.includes(
                    status
                )
        );

    const overall =
        hasError
            ? "attention"
            : hasWarning
                ? "partial"
                : String(
                    systems.overall ||
                    "operational"
                ).toLowerCase();

    const healthy =
        !hasError &&
        !hasWarning &&
        isConnectedStatus(
            overall
        );

    if (el.overallSystemStatus) {
        el.overallSystemStatus.textContent =
            healthy
                ? "Operational"
                : hasError
                    ? "Needs attention"
                    : "Partially ready";

        el.overallSystemStatus.className =
            `status-badge ${
                healthy
                    ? "confirmed"
                    : "pending"
            }`;
    }

    setText(
        el.vapiConnectionStatus,
        connectionText(
            systemStatuses.vapi,
            "Ready for inbound calls"
        )
    );

    setText(
        el.calendarConnectionStatus,
        connectionText(
            systemStatuses.calendar,
            "Booking calendar connected"
        )
    );

    setText(
        el.dvlaConnectionStatus,
        connectionText(
            systemStatuses.dvla,
            "Vehicle lookup available"
        )
    );

    if (el.reminderConnectionStatus) {
        setText(
            el.reminderConnectionStatus,
            connectionText(
                systemStatuses.reminders,
                "Reminder scheduler ready"
            )
        );
    }

    setText(
        el.backendConnectionStatus,
        connectionText(
            systemStatuses.backend,
            "Flask service online"
        )
    );

    setText(
        el.sidebarStatusText,
        healthy
            ? "Garage AI online"
            : hasError
                ? "Garage AI needs attention"
                : "Garage AI partially ready"
    );

    setText(
        el.sidebarStatusDetail,
        healthy
            ? "Voice, calendar, DVLA, reminders and dashboard services are operational."
            : hasError
                ? "One or more business services reported an error."
                : "The dashboard is online, but one or more integrations are not fully configured."
    );

    el.sidebarStatusPulse?.classList.toggle(
        "warning",
        !healthy
    );
}

function openCustomerDrawer(customer) {
    dashboardState.selectedCustomer =
        customer;

    if (!el.customerDrawer) {
        return;
    }

    const name =
        customer.name ||
        customer.customer_name ||
        "Customer";

    const phone =
        customer.phone ||
        customer.customer_phone ||
        "Phone not recorded";

    const email =
        customer.email ||
        customer.customer_email ||
        "Email not recorded";

    const vehicles =
        Array.isArray(
            customer.vehicles
        )
            ? customer.vehicles
            : [];

    const bookings =
        Array.isArray(
            customer.bookings
        )
            ? customer.bookings
            : Array.isArray(
                customer.booking_history
            )
                ? customer.booking_history
                : [];

    const sortedBookings =
        [...bookings].sort(
            (first, second) => {
                const firstDate =
                    parseDate(
                        bookingDateValue(
                            first
                        )
                    );

                const secondDate =
                    parseDate(
                        bookingDateValue(
                            second
                        )
                    );

                return (
                    (secondDate?.getTime() || 0) -
                    (firstDate?.getTime() || 0)
                );
            }
        );

    const bookingCount =
        safeNumber(
            customer.booking_count ??
            customer.total_bookings ??
            bookings.length
        );

    const completedCount =
        safeNumber(
            customer.completed_visit_count ??
            customer.completed_bookings
        );

    const upcomingCount =
        safeNumber(
            customer.upcoming_booking_count ??
            customer.upcoming_bookings
        );

    const cancelledCount =
        safeNumber(
            customer.cancelled_booking_count ??
            customer.cancelled_bookings
        );

    const totalRevenue =
        safeNumber(
            customer.total_revenue ??
            customer.lifetime_value ??
            customer.total_spent
        );

    const lastVisit =
        parseDate(
            customer.last_visit ||
            customer.last_booking_date
        );

    const nextBooking =
        parseDate(
            customer.next_booking ||
            customer.next_booking_date
        );

    setText(
        el.customerDrawerTitle,
        name
    );

    if (el.customerDrawerBody) {
        el.customerDrawerBody.innerHTML = `
            <div class="drawer-profile-header">
                <div class="drawer-profile-avatar">
                    ${getCustomerInitials(
                        name
                    )}
                </div>

                <div>
                    <h3>
                        ${escapeHtml(
                            name
                        )}
                    </h3>

                    <p>
                        ${escapeHtml(
                            phone
                        )}
                    </p>
                </div>
            </div>

            <div class="drawer-detail-grid">
                ${drawerDetail(
                    "Phone",
                    phone
                )}

                ${drawerDetail(
                    "Email",
                    email
                )}

                ${drawerDetail(
                    "Vehicles",
                    formatNumber(
                        vehicles.length
                    )
                )}

                ${drawerDetail(
                    "Total bookings",
                    formatNumber(
                        bookingCount
                    )
                )}

                ${drawerDetail(
                    "Completed visits",
                    formatNumber(
                        completedCount
                    )
                )}

                ${drawerDetail(
                    "Upcoming bookings",
                    formatNumber(
                        upcomingCount
                    )
                )}

                ${drawerDetail(
                    "Cancelled",
                    formatNumber(
                        cancelledCount
                    )
                )}

                ${drawerDetail(
                    "Lifetime value",
                    formatCurrency(
                        totalRevenue
                    )
                )}

                ${drawerDetail(
                    "Last visit",
                    lastVisit
                        ? formatAppointmentDate(
                            lastVisit
                        )
                        : "No completed visit"
                )}

                ${drawerDetail(
                    "Next booking",
                    nextBooking
                        ? formatAppointmentDate(
                            nextBooking
                        )
                        : "No upcoming booking"
                )}
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Vehicles
                    </h4>

                    <span>
                        ${formatNumber(
                            vehicles.length
                        )}
                    </span>
                </div>

                ${
                    vehicles.length
                        ? vehicles
                            .map(
                                (vehicle) => {
                                    const registration =
                                        bookingRegistration(
                                            vehicle
                                        );

                                    const make =
                                        vehicle.make ||
                                        vehicle.vehicle_make ||
                                        "";

                                    const model =
                                        vehicle.model ||
                                        vehicle.vehicle_model ||
                                        "";

                                    const vehicleName =
                                        [
                                            make,
                                            model
                                        ]
                                            .filter(Boolean)
                                            .join(" ") ||
                                        "Vehicle details unavailable";

                                    return `
                                        <button
                                            class="drawer-list-button"
                                            type="button"
                                            data-vehicle-reg="${escapeAttribute(
                                                registration
                                            )}"
                                        >
                                            <span class="drawer-list-icon">
                                                🚗
                                            </span>

                                            <span class="drawer-list-copy">
                                                <strong>
                                                    ${escapeHtml(
                                                        registration
                                                    )}
                                                </strong>

                                                <small>
                                                    ${escapeHtml(
                                                        vehicleName
                                                    )}
                                                </small>
                                            </span>

                                            <span class="drawer-list-arrow">
                                                ›
                                            </span>
                                        </button>
                                    `;
                                }
                            )
                            .join("")
                        : createEmptyState(
                            "🚗",
                            "No vehicles recorded",
                            "Vehicle records will appear when a registration is saved.",
                            true
                        )
                }
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Complete booking history
                    </h4>

                    <span>
                        ${formatNumber(
                            bookingCount
                        )}
                    </span>
                </div>

                ${
                    sortedBookings.length
                        ? sortedBookings
                            .map(
                                (booking) => {
                                    const date =
                                        parseDate(
                                            bookingDateValue(
                                                booking
                                            )
                                        );

                                    const service =
                                        bookingService(
                                            booking
                                        );

                                    const registration =
                                        bookingRegistration(
                                            booking
                                        );

                                    const status =
                                        bookingStatus(
                                            booking
                                        );

                                    const price =
                                        safeNumber(
                                            booking.price ??
                                            booking.revenue ??
                                            booking.value
                                        );

                                    return `
                                        <div class="drawer-history-item">
                                            <div class="drawer-history-icon">
                                                ${getServiceIcon(
                                                    service
                                                )}
                                            </div>

                                            <div class="drawer-history-copy">
                                                <div class="drawer-history-heading">
                                                    <strong>
                                                        ${escapeHtml(
                                                            service
                                                        )}
                                                    </strong>

                                                    <span class="status-badge ${getStatusClass(
                                                        status
                                                    )}">
                                                        ${escapeHtml(
                                                            capitalise(
                                                                status
                                                            )
                                                        )}
                                                    </span>
                                                </div>

                                                <p>
                                                    ${escapeHtml(
                                                        registration
                                                    )}
                                                    ·
                                                    ${
                                                        date
                                                            ? escapeHtml(
                                                                formatAppointmentDate(
                                                                    date
                                                                )
                                                            )
                                                            : "Date unavailable"
                                                    }
                                                </p>

                                                ${
                                                    price > 0
                                                        ? `
                                                            <small>
                                                                ${escapeHtml(
                                                                    formatCurrency(
                                                                        price
                                                                    )
                                                                )}
                                                            </small>
                                                        `
                                                        : ""
                                                }
                                            </div>
                                        </div>
                                    `;
                                }
                            )
                            .join("")
                        : createEmptyState(
                            "📅",
                            "No bookings recorded",
                            "Booking history will appear here.",
                            true
                        )
                }
            </div>
        `;
    }

    openDrawer(
        el.customerDrawer
    );
}

function findVehicle(registration) {
    const normalisedRegistration =
        String(registration || "")
            .replace(/[^A-Z0-9]/gi, "")
            .toUpperCase();

    if (!normalisedRegistration) {
        return null;
    }

    const apiVehicles =
        Array.isArray(
            dashboardState.data.vehicles
        )
            ? dashboardState.data.vehicles
            : [];

    const apiVehicle =
        apiVehicles.find(
            (vehicle) => {
                const vehicleRegistration =
                    String(
                        vehicle.registration_key ||
                        vehicle.registration ||
                        vehicle.vehicle_reg ||
                        vehicle.reg ||
                        ""
                    )
                        .replace(/[^A-Z0-9]/gi, "")
                        .toUpperCase();

                return (
                    vehicleRegistration ===
                    normalisedRegistration
                );
            }
        );

    if (apiVehicle) {
        return apiVehicle;
    }

    for (
        const customer of getCustomerRecords()
    ) {
        const vehicles =
            Array.isArray(
                customer.vehicles
            )
                ? customer.vehicles
                : [];

        const vehicle =
            vehicles.find(
                (item) => {
                    const vehicleRegistration =
                        String(
                            item.registration_key ||
                            item.registration ||
                            item.vehicle_reg ||
                            item.reg ||
                            ""
                        )
                            .replace(/[^A-Z0-9]/gi, "")
                            .toUpperCase();

                    return (
                        vehicleRegistration ===
                        normalisedRegistration
                    );
                }
            );

        if (vehicle) {
            return {
                ...vehicle,

                customer_name:
                    vehicle.customer_name ||
                    customer.name ||
                    customer.customer_name ||
                    "Customer",

                customer_phone:
                    vehicle.customer_phone ||
                    customer.phone ||
                    customer.customer_phone ||
                    "",

                customer_email:
                    vehicle.customer_email ||
                    customer.email ||
                    customer.customer_email ||
                    "",

                bookings:
                    Array.isArray(
                        vehicle.bookings
                    )
                        ? vehicle.bookings
                        : Array.isArray(
                            vehicle.booking_history
                        )
                            ? vehicle.booking_history
                            : [],

                booking_history:
                    Array.isArray(
                        vehicle.booking_history
                    )
                        ? vehicle.booking_history
                        : Array.isArray(
                            vehicle.bookings
                        )
                            ? vehicle.bookings
                            : []
            };
        }
    }

    const allBookings = [
        ...(
            Array.isArray(
                dashboardState.data.booking_history
            )
                ? dashboardState.data.booking_history
                : []
        ),

        ...(
            Array.isArray(
                dashboardState.data.upcoming_appointments
            )
                ? dashboardState.data.upcoming_appointments
                : []
        )
    ];

    const matchingBookings =
        allBookings.filter(
            (booking) => {
                const bookingRegistrationValue =
                    String(
                        booking.registration_key ||
                        booking.vehicle_reg ||
                        booking.registration ||
                        booking.reg ||
                        ""
                    )
                        .replace(/[^A-Z0-9]/gi, "")
                        .toUpperCase();

                return (
                    bookingRegistrationValue ===
                    normalisedRegistration
                );
            }
        );

    if (!matchingBookings.length) {
        return null;
    }

    const latestBooking =
        [...matchingBookings].sort(
            (first, second) => {
                const firstDate =
                    parseDate(
                        bookingDateValue(first)
                    );

                const secondDate =
                    parseDate(
                        bookingDateValue(second)
                    );

                return (
                    (secondDate?.getTime() || 0) -
                    (firstDate?.getTime() || 0)
                );
            }
        )[0];

    return {
        ...latestBooking,

        registration:
            bookingRegistration(
                latestBooking
            ),

        vehicle_reg:
            bookingRegistration(
                latestBooking
            ),

        bookings:
            matchingBookings,

        booking_history:
            matchingBookings,

        booking_count:
            matchingBookings.length
    };
}

function openVehicleDrawer(vehicle) {
    dashboardState.selectedVehicle =
        vehicle;

    if (!el.vehicleDrawer) {
        return;
    }

    const registration =
        bookingRegistration(vehicle);

    const make =
        vehicle.make ||
        vehicle.vehicle_make ||
        "Unknown";

    const model =
        vehicle.model ||
        vehicle.vehicle_model ||
        "Unknown";

    const vehicleName =
        [make, model]
            .filter(
                (value) =>
                    value &&
                    value !== "Unknown"
            )
            .join(" ") ||
        "Vehicle details unavailable";

    const colour =
        vehicle.colour ||
        vehicle.color ||
        vehicle.vehicle_colour ||
        "Unknown";

    const year =
        vehicle.year ||
        vehicle.manufacture_year ||
        vehicle.year_of_manufacture ||
        "Unknown";

    const fuel =
        vehicle.fuel_type ||
        vehicle.fuel ||
        "Unknown";

    const motStatus =
        vehicle.mot_status ||
        vehicle.motStatus ||
        "Not loaded";

    const motExpiry =
        parseDate(
            vehicle.mot_expiry_date ||
            vehicle.mot_expiry ||
            vehicle.mot_due_date
        );

    const owner =
        vehicle.customer_name ||
        vehicle.owner_name ||
        vehicle.name ||
        "Customer";

    const ownerPhone =
        vehicle.customer_phone ||
        vehicle.owner_phone ||
        vehicle.phone ||
        "Phone not recorded";

    const ownerEmail =
        vehicle.customer_email ||
        vehicle.owner_email ||
        vehicle.email ||
        "Email not recorded";

    const history =
        Array.isArray(
            vehicle.booking_history
        )
            ? vehicle.booking_history
            : Array.isArray(
                vehicle.bookings
            )
                ? vehicle.bookings
                : Array.isArray(
                    vehicle.service_history
                )
                    ? vehicle.service_history
                    : [];

    const sortedHistory =
        [...history].sort(
            (first, second) => {
                const firstDate =
                    parseDate(
                        bookingDateValue(
                            first
                        )
                    );

                const secondDate =
                    parseDate(
                        bookingDateValue(
                            second
                        )
                    );

                return (
                    (secondDate?.getTime() || 0) -
                    (firstDate?.getTime() || 0)
                );
            }
        );

    const visitCount =
        safeNumber(
            vehicle.booking_count ??
            vehicle.total_bookings ??
            vehicle.visit_count ??
            history.length
        );

    const completedVisitCount =
        safeNumber(
            vehicle.completed_visit_count ??
            vehicle.completed_bookings
        );

    const upcomingBookingCount =
        safeNumber(
            vehicle.upcoming_booking_count ??
            vehicle.upcoming_bookings
        );

    const totalRevenue =
        safeNumber(
            vehicle.total_revenue ??
            vehicle.total_spent ??
            vehicle.lifetime_value
        );

    const lastVisit =
        parseDate(
            vehicle.last_visit ||
            vehicle.last_booking_date ||
            vehicle.last_service_date
        );

    const nextBooking =
        parseDate(
            vehicle.next_booking ||
            vehicle.next_booking_date ||
            vehicle.next_appointment
        );

    setText(
        el.vehicleDrawerTitle,
        registration
    );

    if (el.vehicleDrawerBody) {
        el.vehicleDrawerBody.innerHTML = `
            <div class="vehicle-drawer-hero">
                <div class="vehicle-drawer-icon">
                    🚗
                </div>

                <div>
                    <span class="vehicle-registration">
                        ${escapeHtml(
                            registration
                        )}
                    </span>

                    <h3>
                        ${escapeHtml(
                            vehicleName
                        )}
                    </h3>

                    <p>
                        Owned by
                        ${escapeHtml(
                            owner
                        )}
                    </p>
                </div>
            </div>

            <div class="drawer-detail-grid">
                ${drawerDetail(
                    "Owner",
                    owner
                )}

                ${drawerDetail(
                    "Owner phone",
                    ownerPhone
                )}

                ${drawerDetail(
                    "Owner email",
                    ownerEmail
                )}

                ${drawerDetail(
                    "Make",
                    make
                )}

                ${drawerDetail(
                    "Model",
                    model
                )}

                ${drawerDetail(
                    "Year",
                    year
                )}

                ${drawerDetail(
                    "Colour",
                    colour
                )}

                ${drawerDetail(
                    "Fuel",
                    fuel
                )}

                ${drawerDetail(
                    "MOT status",
                    motStatus
                )}

                ${drawerDetail(
                    "MOT expiry",
                    motExpiry
                        ? formatAppointmentDate(
                            motExpiry
                        )
                        : "Not recorded"
                )}
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Vehicle performance
                    </h4>
                </div>

                <div class="drawer-detail-grid">
                    ${drawerDetail(
                        "Total visits",
                        formatNumber(
                            visitCount
                        )
                    )}

                    ${drawerDetail(
                        "Completed visits",
                        formatNumber(
                            completedVisitCount
                        )
                    )}

                    ${drawerDetail(
                        "Upcoming bookings",
                        formatNumber(
                            upcomingBookingCount
                        )
                    )}

                    ${drawerDetail(
                        "Total spent",
                        formatCurrency(
                            totalRevenue
                        )
                    )}

                    ${drawerDetail(
                        "Last visit",
                        lastVisit
                            ? formatAppointmentDate(
                                lastVisit
                            )
                            : "No completed visit"
                    )}

                    ${drawerDetail(
                        "Next booking",
                        nextBooking
                            ? formatAppointmentDate(
                                nextBooking
                            )
                            : "No upcoming booking"
                    )}
                </div>
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Complete service history
                    </h4>

                    <span>
                        ${formatNumber(
                            visitCount
                        )}
                    </span>
                </div>

                ${
                    sortedHistory.length
                        ? sortedHistory
                            .map(
                                (booking) => {
                                    const date =
                                        parseDate(
                                            bookingDateValue(
                                                booking
                                            )
                                        );

                                    const service =
                                        bookingService(
                                            booking
                                        );

                                    const status =
                                        bookingStatus(
                                            booking
                                        );

                                    const customer =
                                        bookingCustomer(
                                            booking
                                        );

                                    const price =
                                        safeNumber(
                                            booking.price ??
                                            booking.revenue ??
                                            booking.value
                                        );

                                    return `
                                        <div class="drawer-history-item">
                                            <div class="drawer-history-icon">
                                                ${getServiceIcon(
                                                    service
                                                )}
                                            </div>

                                            <div class="drawer-history-copy">
                                                <div class="drawer-history-heading">
                                                    <strong>
                                                        ${escapeHtml(
                                                            service
                                                        )}
                                                    </strong>

                                                    <span class="status-badge ${getStatusClass(
                                                        status
                                                    )}">
                                                        ${escapeHtml(
                                                            capitalise(
                                                                status
                                                            )
                                                        )}
                                                    </span>
                                                </div>

                                                <p>
                                                    ${escapeHtml(
                                                        customer
                                                    )}
                                                    ·
                                                    ${
                                                        date
                                                            ? escapeHtml(
                                                                formatAppointmentDate(
                                                                    date
                                                                )
                                                            )
                                                            : "Date unavailable"
                                                    }
                                                </p>

                                                ${
                                                    price > 0
                                                        ? `
                                                            <small>
                                                                ${escapeHtml(
                                                                    formatCurrency(
                                                                        price
                                                                    )
                                                                )}
                                                            </small>
                                                        `
                                                        : ""
                                                }
                                            </div>
                                        </div>
                                    `;
                                }
                            )
                            .join("")
                        : createEmptyState(
                            "🔧",
                            "No service history recorded",
                            "Completed and upcoming visits for this registration will appear here.",
                            true
                        )
                }
            </div>
        `;
    }

    openDrawer(
        el.vehicleDrawer
    );
}

function openRevenueCentre() {
    const revenue =
        dashboardState.data.revenue || {};

    const monthlyBreakdown =
        Array.isArray(
            revenue.monthly_breakdown
        )
            ? revenue.monthly_breakdown
            : [];

    let modal =
        document.getElementById(
            "revenueCentreModal"
        );

    if (!modal) {
        modal =
            document.createElement(
                "div"
            );

        modal.id =
            "revenueCentreModal";

        modal.className =
            "dashboard-modal";

        modal.setAttribute(
            "role",
            "dialog"
        );

        modal.setAttribute(
            "aria-modal",
            "true"
        );

        modal.setAttribute(
            "aria-hidden",
            "true"
        );

        modal.innerHTML = `
            <div class="dashboard-modal-card revenue-centre-modal-card">
                <header class="dashboard-modal-header">
                    <div>
                        <span class="detail-drawer-eyebrow">
                            Financial performance
                        </span>

                        <h2>
                            Revenue Centre
                        </h2>
                    </div>

                    <button
                        class="drawer-close-button"
                        type="button"
                        data-close-revenue-centre
                        aria-label="Close Revenue Centre"
                    >
                        ×
                    </button>
                </header>

                <div
                    id="revenueCentreBody"
                    class="dashboard-modal-body"
                ></div>
            </div>
        `;

        document.body.appendChild(
            modal
        );

        modal
            .querySelector(
                "[data-close-revenue-centre]"
            )
            ?.addEventListener(
                "click",
                closeRevenueCentre
            );

        modal.addEventListener(
            "click",
            (event) => {
                if (
                    event.target === modal
                ) {
                    closeRevenueCentre();
                }
            }
        );
    }

    const body =
        modal.querySelector(
            "#revenueCentreBody"
        );

    const todayRevenue =
        safeNumber(
            revenue.today
        );

    const weekRevenue =
        safeNumber(
            revenue.this_week ??
            revenue.week
        );

    const monthRevenue =
        safeNumber(
            revenue.this_month ??
            revenue.month
        );

    const yearRevenue =
        safeNumber(
            revenue.this_year ??
            revenue.year
        );

    const lifetimeRevenue =
        safeNumber(
            revenue.lifetime ??
            revenue.total
        );

    const pipelineRevenue =
        safeNumber(
            revenue.future_pipeline ??
            revenue.pipeline
        );

    const averageBookingValue =
        safeNumber(
            revenue.average_booking_value ??
            revenue.average
        );

    const completedBookings =
        safeNumber(
            revenue.completed_booking_count ??
            revenue.completed_bookings
        );

    if (body) {
        body.innerHTML = `
            <div class="revenue-centre-summary">
                <div class="revenue-centre-highlight">
                    <span>
                        This month
                    </span>

                    <strong>
                        ${escapeHtml(
                            formatCurrency(
                                monthRevenue
                            )
                        )}
                    </strong>

                    <small>
                        Estimated from recorded garage bookings
                    </small>
                </div>

                <div class="revenue-centre-stat-grid">
                    <div class="revenue-centre-stat">
                        <span>
                            Today
                        </span>

                        <strong>
                            ${escapeHtml(
                                formatCurrency(
                                    todayRevenue
                                )
                            )}
                        </strong>
                    </div>

                    <div class="revenue-centre-stat">
                        <span>
                            This week
                        </span>

                        <strong>
                            ${escapeHtml(
                                formatCurrency(
                                    weekRevenue
                                )
                            )}
                        </strong>
                    </div>

                    <div class="revenue-centre-stat">
                        <span>
                            This year
                        </span>

                        <strong>
                            ${escapeHtml(
                                formatCurrency(
                                    yearRevenue
                                )
                            )}
                        </strong>
                    </div>

                    <div class="revenue-centre-stat">
                        <span>
                            Lifetime
                        </span>

                        <strong>
                            ${escapeHtml(
                                formatCurrency(
                                    lifetimeRevenue
                                )
                            )}
                        </strong>
                    </div>

                    <div class="revenue-centre-stat">
                        <span>
                            Future pipeline
                        </span>

                        <strong>
                            ${escapeHtml(
                                formatCurrency(
                                    pipelineRevenue
                                )
                            )}
                        </strong>
                    </div>

                    <div class="revenue-centre-stat">
                        <span>
                            Average booking
                        </span>

                        <strong>
                            ${escapeHtml(
                                formatCurrency(
                                    averageBookingValue
                                )
                            )}
                        </strong>
                    </div>
                </div>
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Revenue overview
                    </h4>
                </div>

                <div class="drawer-detail-grid">
                    ${drawerDetail(
                        "Completed bookings",
                        formatNumber(
                            completedBookings
                        )
                    )}

                    ${drawerDetail(
                        "Future booked work",
                        formatCurrency(
                            pipelineRevenue
                        )
                    )}

                    ${drawerDetail(
                        "Average booking value",
                        formatCurrency(
                            averageBookingValue
                        )
                    )}

                    ${drawerDetail(
                        "Total recorded revenue",
                        formatCurrency(
                            lifetimeRevenue
                        )
                    )}
                </div>
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Last six months
                    </h4>

                    <span>
                        Revenue trend
                    </span>
                </div>

                <div class="revenue-month-list">
                    ${
                        monthlyBreakdown.length
                            ? monthlyBreakdown
                                .map(
                                    (month) => {
                                        const amount =
                                            safeNumber(
                                                month.revenue ??
                                                month.total ??
                                                month.value
                                            );

                                        const maximum =
                                            Math.max(
                                                1,
                                                ...monthlyBreakdown.map(
                                                    (item) =>
                                                        safeNumber(
                                                            item.revenue ??
                                                            item.total ??
                                                            item.value
                                                        )
                                                )
                                            );

                                        const percentage =
                                            Math.max(
                                                4,
                                                Math.round(
                                                    (
                                                        amount /
                                                        maximum
                                                    ) *
                                                    100
                                                )
                                            );

                                        return `
                                            <div class="revenue-month-row">
                                                <span class="revenue-month-label">
                                                    ${escapeHtml(
                                                        month.label ||
                                                        "Month"
                                                    )}
                                                </span>

                                                <span class="revenue-month-track">
                                                    <span
                                                        class="revenue-month-bar"
                                                        style="width: ${percentage}%;"
                                                    ></span>
                                                </span>

                                                <strong>
                                                    ${escapeHtml(
                                                        formatCurrency(
                                                            amount
                                                        )
                                                    )}
                                                </strong>
                                            </div>
                                        `;
                                    }
                                )
                                .join("")
                            : createEmptyState(
                                "£",
                                "No revenue history loaded",
                                "Monthly revenue will appear as booking history is recorded.",
                                true
                            )
                    }
                </div>
            </div>

            <div class="drawer-note">
                Revenue is estimated using the configured service prices
                attached to recorded bookings. Cancelled bookings are excluded.
            </div>
        `;
    }

    modal.classList.add(
        "visible"
    );

    modal.setAttribute(
        "aria-hidden",
        "false"
    );

    document.body.classList.add(
        "modal-open"
    );
}

function closeRevenueCentre() {
    const modal =
        document.getElementById(
            "revenueCentreModal"
        );

    modal?.classList.remove(
        "visible"
    );

    modal?.setAttribute(
        "aria-hidden",
        "true"
    );

    document.body.classList.remove(
        "modal-open"
    );
}

function openReminderDrawer() {
    const reminders =
        dashboardState.data.reminders || {};

    const queue =
        Array.isArray(reminders.queue)
            ? reminders.queue
            : [];

    const recent =
        Array.isArray(reminders.recent)
            ? reminders.recent
            : [];

    const waiting =
        safeNumber(
            reminders.waiting ??
            reminders.pending ??
            reminders.due
        );

    const due =
        safeNumber(
            reminders.due
        );

    const sent =
        safeNumber(
            reminders.sent_this_month ??
            reminders.sent
        );

    const failed =
        safeNumber(
            reminders.failed
        );

    const lastRun =
        parseDate(
            reminders.last_run
        );

    const nextRun =
        parseDate(
            reminders.next_run
        );

    const status =
        String(
            reminders.status ||
            "ready"
        ).toLowerCase();

    setText(
        el.reminderCentreWaiting,
        formatNumber(waiting)
    );

    setText(
        el.reminderCentreSent,
        formatNumber(sent)
    );

    setText(
        el.reminderCentreFailed,
        formatNumber(failed)
    );

    setText(
        el.reminderDrawerTitle,
        "Reminder Centre"
    );

    if (el.reminderQueueList) {
        el.reminderQueueList.innerHTML = `
            <div class="drawer-detail-grid reminder-centre-detail-grid">
                ${drawerDetail(
                    "Due now",
                    formatNumber(due)
                )}

                ${drawerDetail(
                    "Waiting",
                    formatNumber(waiting)
                )}

                ${drawerDetail(
                    "Sent this month",
                    formatNumber(sent)
                )}

                ${drawerDetail(
                    "Failed",
                    formatNumber(failed)
                )}

                ${drawerDetail(
                    "Last run",
                    lastRun
                        ? formatAppointmentDate(lastRun)
                        : "Not recorded"
                )}

                ${drawerDetail(
                    "Next run",
                    nextRun
                        ? formatAppointmentDate(nextRun)
                        : "Automatic schedule"
                )}
            </div>

            <div class="drawer-note">
                Scheduler status:
                <strong>
                    ${escapeHtml(
                        capitalise(status)
                    )}
                </strong>
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Reminder queue
                    </h4>

                    <span>
                        ${formatNumber(
                            queue.length
                        )}
                    </span>
                </div>

                ${
                    queue.length
                        ? queue
                            .slice(0, 20)
                            .map(
                                (reminder) => {
                                    const customer =
                                        reminder.customer_name ||
                                        reminder.name ||
                                        "Customer";

                                    const service =
                                        reminder.service ||
                                        reminder.service_name ||
                                        reminder.type ||
                                        "Garage reminder";

                                    const registration =
                                        reminder.vehicle_reg ||
                                        reminder.registration ||
                                        reminder.reg ||
                                        "";

                                    const sendDate =
                                        parseDate(
                                            reminder.send_at ||
                                            reminder.datetime ||
                                            reminder.date ||
                                            reminder.due_at
                                        );

                                    const reminderStatus =
                                        String(
                                            reminder.status ||
                                            "pending"
                                        ).toLowerCase();

                                    const reminderType =
                                        reminder.reminder_type ||
                                        reminder.template ||
                                        reminder.kind ||
                                        "Reminder";

                                    return `
                                        <div class="reminder-queue-item">
                                            <div class="reminder-queue-icon">
                                                🔔
                                            </div>

                                            <div class="reminder-queue-copy">
                                                <div class="reminder-queue-heading">
                                                    <strong>
                                                        ${escapeHtml(
                                                            customer
                                                        )}
                                                    </strong>

                                                    <span class="status-badge ${getStatusClass(
                                                        reminderStatus
                                                    )}">
                                                        ${escapeHtml(
                                                            capitalise(
                                                                reminderStatus
                                                            )
                                                        )}
                                                    </span>
                                                </div>

                                                <span>
                                                    ${escapeHtml(
                                                        reminderType
                                                    )}
                                                    ·
                                                    ${escapeHtml(
                                                        service
                                                    )}
                                                </span>

                                                ${
                                                    registration
                                                        ? `
                                                            <small>
                                                                ${escapeHtml(
                                                                    registration
                                                                )}
                                                            </small>
                                                        `
                                                        : ""
                                                }

                                                <small>
                                                    ${
                                                        sendDate
                                                            ? escapeHtml(
                                                                formatAppointmentDate(
                                                                    sendDate
                                                                )
                                                            )
                                                            : "Schedule not recorded"
                                                    }
                                                </small>
                                            </div>
                                        </div>
                                    `;
                                }
                            )
                            .join("")
                        : createEmptyState(
                            "🔔",
                            "No reminders waiting",
                            "The reminder queue is currently clear.",
                            true
                        )
                }
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Recent reminder activity
                    </h4>

                    <span>
                        ${formatNumber(
                            recent.length
                        )}
                    </span>
                </div>

                ${
                    recent.length
                        ? recent
                            .slice(0, 10)
                            .map(
                                (item) => {
                                    const customer =
                                        item.customer_name ||
                                        item.name ||
                                        "Customer";

                                    const itemStatus =
                                        String(
                                            item.status ||
                                            "sent"
                                        ).toLowerCase();

                                    const itemDate =
                                        parseDate(
                                            item.sent_at ||
                                            item.updated_at ||
                                            item.created_at ||
                                            item.date
                                        );

                                    return `
                                        <div class="reminder-queue-item">
                                            <div class="reminder-queue-icon">
                                                ${
                                                    itemStatus === "failed"
                                                        ? "⚠️"
                                                        : "✅"
                                                }
                                            </div>

                                            <div class="reminder-queue-copy">
                                                <div class="reminder-queue-heading">
                                                    <strong>
                                                        ${escapeHtml(
                                                            customer
                                                        )}
                                                    </strong>

                                                    <span class="status-badge ${getStatusClass(
                                                        itemStatus
                                                    )}">
                                                        ${escapeHtml(
                                                            capitalise(
                                                                itemStatus
                                                            )
                                                        )}
                                                    </span>
                                                </div>

                                                <span>
                                                    ${escapeHtml(
                                                        item.message ||
                                                        item.detail ||
                                                        item.reminder_type ||
                                                        "Reminder activity"
                                                    )}
                                                </span>

                                                <small>
                                                    ${
                                                        itemDate
                                                            ? escapeHtml(
                                                                formatAppointmentDate(
                                                                    itemDate
                                                                )
                                                            )
                                                            : "Time unavailable"
                                                    }
                                                </small>
                                            </div>
                                        </div>
                                    `;
                                }
                            )
                            .join("")
                        : createEmptyState(
                            "📨",
                            "No recent reminder activity",
                            "Sent and failed reminder records will appear here when available.",
                            true
                        )
                }
            </div>
        `;
    }

    openDrawer(
        el.reminderDrawer
    );
}

function openBookingModal(booking) {
    dashboardState.selectedBooking =
        booking;

    if (!el.bookingDetailsModal) {
        return;
    }

    const customer =
        bookingCustomer(booking);

    const phone =
        bookingPhone(booking);

    const registration =
        bookingRegistration(booking);

    const service =
        bookingService(booking);

    const status =
        bookingStatus(booking);

    const date =
        parseDate(
            bookingDateValue(booking)
        );

    setText(
        el.bookingDetailsTitle,
        `${service} booking`
    );

    if (el.bookingDetailsBody) {
        el.bookingDetailsBody.innerHTML = `
            <div class="booking-modal-summary">
                <div class="booking-modal-icon">
                    📅
                </div>

                <div>
                    <h3>
                        ${escapeHtml(customer)}
                    </h3>

                    <p>
                        ${escapeHtml(service)}
                    </p>
                </div>

                <span class="status-badge ${getStatusClass(
                    status
                )}">
                    ${escapeHtml(
                        capitalise(status)
                    )}
                </span>
            </div>

            <div class="drawer-detail-grid">
                ${drawerDetail(
                    "Customer",
                    customer
                )}

                ${drawerDetail(
                    "Phone",
                    phone
                )}

                ${drawerDetail(
                    "Vehicle",
                    registration
                )}

                ${drawerDetail(
                    "Service",
                    service
                )}

                ${drawerDetail(
                    "Date and time",
                    date
                        ? formatAppointmentDate(
                            date
                        )
                        : "Date unavailable"
                )}

                ${drawerDetail(
                    "Status",
                    capitalise(status)
                )}
            </div>

            ${
                booking.notes ||
                booking.description
                    ? `
                        <div class="drawer-section">
                            <div class="drawer-section-header">
                                <h4>
                                    Booking notes
                                </h4>
                            </div>

                            <div class="drawer-note">
                                ${escapeHtml(
                                    booking.notes ||
                                    booking.description
                                )}
                            </div>
                        </div>
                    `
                    : ""
            }
        `;
    }

    el.bookingDetailsModal.classList.add(
        "visible"
    );

    el.bookingDetailsModal.setAttribute(
        "aria-hidden",
        "false"
    );

    document.body.classList.add(
        "modal-open"
    );
}

function closeBookingModal() {
    el.bookingDetailsModal?.classList.remove(
        "visible"
    );

    el.bookingDetailsModal?.setAttribute(
        "aria-hidden",
        "true"
    );

    document.body.classList.remove(
        "modal-open"
    );

    dashboardState.selectedBooking =
        null;
}

function bookingCustomer(booking) {
    return String(
        booking.customer_name ||
        booking.name ||
        "Customer"
    ).trim();
}

function bookingPhone(booking) {
    return String(
        booking.phone ||
        booking.customer_phone ||
        "Phone not recorded"
    ).trim();
}

function bookingRegistration(booking) {
    return String(
        booking.vehicle_reg ||
        booking.registration ||
        booking.reg ||
        "—"
    )
        .trim()
        .toUpperCase();
}

function bookingService(booking) {
    return String(
        booking.service ||
        booking.service_name ||
        "Garage appointment"
    ).trim();
}

function bookingStatus(booking) {
    return String(
        booking.status ||
        "confirmed"
    )
        .trim()
        .toLowerCase();
}

function bookingDateValue(booking) {
    return (
        booking.start ||
        booking.datetime ||
        booking.date_time ||
        booking.date ||
        null
    );
}

function customerKey(customer) {
    return [
        customer.name ||
        customer.customer_name ||
        "",
        customer.phone ||
        customer.customer_phone ||
        ""
    ]
        .join("|")
        .trim()
        .toLowerCase();
}

function drawerDetail(label, value) {
    return `
        <div class="drawer-detail-card">
            <span>
                ${escapeHtml(label)}
            </span>

            <strong>
                ${escapeHtml(
                    String(
                        value ??
                        "Not recorded"
                    )
                )}
            </strong>
        </div>
    `;
}

function setButtonLoading(
    button,
    loading
) {
    if (!button) {
        return;
    }

    button.disabled =
        loading;

    button.classList.toggle(
        "loading",
        loading
    );

    button.setAttribute(
        "aria-busy",
        String(loading)
    );
}

function showToast(
    title,
    message,
    type = "info"
) {
    if (!el.toastContainer) {
        return;
    }

    const toast =
        document.createElement("div");

    const icon =
        type === "success"
            ? "✓"
            : type === "error"
                ? "!"
                : "i";

    toast.className =
        `toast ${type}`;

    toast.setAttribute(
        "role",
        "status"
    );

    toast.innerHTML = `
        <div class="toast-icon">
            ${icon}
        </div>

        <div class="toast-copy">
            <h4>
                ${escapeHtml(title)}
            </h4>

            <p>
                ${escapeHtml(message)}
            </p>
        </div>
    `;

    el.toastContainer.appendChild(
        toast
    );

    window.setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform =
            "translateY(10px)";

        window.setTimeout(
            () => toast.remove(),
            250
        );
    }, 4200);
}

function createEmptyState(
    icon,
    title,
    message,
    compact = false
) {
    return `
        <div class="empty-state ${
            compact
                ? "compact"
                : ""
        }">
            <div class="empty-state-icon">
                ${icon}
            </div>

            <h4>
                ${escapeHtml(title)}
            </h4>

            <p>
                ${escapeHtml(message)}
            </p>
        </div>
    `;
}

function setText(element, value) {
    if (element) {
        element.textContent =
            String(value ?? "");
    }
}

function getServiceIcon(name) {
    const value =
        String(name)
            .trim()
            .toLowerCase();

    if (SERVICE_ICONS[value]) {
        return SERVICE_ICONS[value];
    }

    const match =
        Object.entries(
            SERVICE_ICONS
        ).find(
            ([key]) =>
                value.includes(key)
        );

    return match
        ? match[1]
        : "🔧";
}

function getActivityIcon(type) {
    return (
        ACTIVITY_ICONS[type] ||
        "🤖"
    );
}

function getStatusClass(status) {
    const value =
        String(status)
            .toLowerCase();

    if (
        value.includes("cancel") ||
        value.includes("fail")
    ) {
        return "cancelled";
    }

    if (
        value.includes("complete") ||
        value.includes("sent")
    ) {
        return "completed";
    }

    if (
        value.includes("pending") ||
        value.includes("waiting") ||
        value.includes("provisional")
    ) {
        return "pending";
    }

    return "confirmed";
}

function getCustomerInitials(name) {
    const words =
        String(name)
            .trim()
            .split(/\s+/)
            .filter(Boolean);

    if (!words.length) {
        return "CU";
    }

    return words
        .slice(0, 2)
        .map(
            (word) =>
                word
                    .charAt(0)
                    .toUpperCase()
        )
        .join("");
}

function isConnectedStatus(status) {
    return [
        "operational",
        "online",
        "connected",
        "healthy",
        "ready",
        "active",
        "true"
    ].includes(
        String(status || "")
            .toLowerCase()
    );
}

function connectionText(
    value,
    connectedText
) {
    const status =
        String(
            value ||
            "connected"
        ).toLowerCase();

    if (
        isConnectedStatus(status)
    ) {
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
        return `${capitalise(
            status
        )} — check configuration`;
    }

    return capitalise(status);
}

function safeNumber(value) {
    const number =
        Number(value);

    return Number.isFinite(number)
        ? number
        : 0;
}

function formatNumber(value) {
    return new Intl.NumberFormat(
        "en-GB"
    ).format(
        safeNumber(value)
    );
}

function formatCurrency(value) {
    const amount =
        Number(value);

    if (!Number.isFinite(amount)) {
        return "£0";
    }

    return new Intl.NumberFormat(
        "en-GB",
        {
            style: "currency",
            currency: "GBP",
            maximumFractionDigits:
                Number.isInteger(
                    amount
                )
                    ? 0
                    : 2
        }
    ).format(amount);
}

function parseDate(value) {
    if (!value) {
        return null;
    }

    const date =
        value instanceof Date
            ? value
            : new Date(value);

    return Number.isNaN(
        date.getTime()
    )
        ? null
        : date;
}

function formatTime(date) {
    return new Intl.DateTimeFormat(
        "en-GB",
        {
            hour: "2-digit",
            minute: "2-digit",
            hour12: true
        }
    )
        .format(date)
        .replace("am", "AM")
        .replace("pm", "PM");
}

function formatAppointmentDate(date) {
    return new Intl.DateTimeFormat(
        "en-GB",
        {
            weekday: "short",
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
            hour12: true
        }
    )
        .format(date)
        .replace("am", "AM")
        .replace("pm", "PM");
}

function formatRelativeTime(date) {
    const difference =
        date.getTime() -
        Date.now();

    const absolute =
        Math.abs(difference);

    const formatter =
        new Intl.RelativeTimeFormat(
            "en-GB",
            {
                numeric: "auto"
            }
        );

    if (
        absolute <
        60 * 1000
    ) {
        return formatter.format(
            Math.round(
                difference / 1000
            ),
            "second"
        );
    }

    if (
        absolute <
        60 * 60 * 1000
    ) {
        return formatter.format(
            Math.round(
                difference /
                (60 * 1000)
            ),
            "minute"
        );
    }

    if (
        absolute <
        24 * 60 * 60 * 1000
    ) {
        return formatter.format(
            Math.round(
                difference /
                (
                    60 *
                    60 *
                    1000
                )
            ),
            "hour"
        );
    }

    return formatter.format(
        Math.round(
            difference /
            (
                24 *
                60 *
                60 *
                1000
            )
        ),
        "day"
    );
}

function localDateKey(date) {
    if (!(date instanceof Date)) {
        return "";
    }

    const year =
        date.getFullYear();

    const month =
        String(
            date.getMonth() + 1
        ).padStart(2, "0");

    const day =
        String(
            date.getDate()
        ).padStart(2, "0");

    return `${year}-${month}-${day}`;
}

function capitalise(value) {
    const text =
        String(value || "")
            .trim();

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
        .replace(
            /&/g,
            "&amp;"
        )
        .replace(
            /</g,
            "&lt;"
        )
        .replace(
            />/g,
            "&gt;"
        )
        .replace(
            /"/g,
            "&quot;"
        )
        .replace(
            /'/g,
            "&#039;"
        );
}

function escapeAttribute(value) {
    return escapeHtml(
        String(value ?? "")
    );
}