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
        "overallSystemStatus",
        "sidebarStatusPulse",
        "sidebarStatusText",
        "sidebarStatusDetail",
        "vapiConnectionStatus",
        "calendarConnectionStatus",
        "dvlaConnectionStatus",
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

        customers:
            Array.isArray(data.customers)
                ? data.customers
                : [],

        reminders: {
            ...defaults.reminders,
            ...(data.reminders || {})
        },

        ai_activity:
            Array.isArray(data.ai_activity)
                ? data.ai_activity
                : [],

        systems: {
            ...defaults.systems,
            ...(data.systems || {})
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
    const bookingButton =
        event.target.closest("[data-booking-index]");

    if (bookingButton) {
        const booking = filteredBookings()[
            Number(bookingButton.dataset.bookingIndex)
        ];

        if (booking) {
            openBookingModal(booking);
        }

        return;
    }

    const customerButton =
        event.target.closest("[data-customer-key]");

    if (customerButton) {
        const customer = getCustomerRecords().find(
            (item) =>
                customerKey(item) ===
                customerButton.dataset.customerKey
        );

        if (customer) {
            openCustomerDrawer(customer);
        }

        return;
    }

    const vehicleButton =
        event.target.closest("[data-vehicle-reg]");

    if (vehicleButton) {
        const vehicle = findVehicle(
            vehicleButton.dataset.vehicleReg
        );

        if (vehicle) {
            openVehicleDrawer(vehicle);
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
        return scrollToSection("reports");
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
        dashboardState.data.reminders;

    const enabled =
        reminders.enabled !== false;

    const due =
        safeNumber(
            reminders.due ??
            reminders.waiting
        );

    const sent =
        safeNumber(
            reminders.sent_this_month ??
            reminders.sent
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

    if (el.reminderSystemBadge) {
        el.reminderSystemBadge.textContent =
            enabled
                ? "Active"
                : "Disabled";

        el.reminderSystemBadge.className =
            `status-badge ${
                enabled
                    ? "confirmed"
                    : "cancelled"
            }`;
    }

    setText(
        el.schedulerStatus,
        capitalise(status)
    );

    setText(
        el.remindersWaitingValue,
        formatNumber(due)
    );

    setText(
        el.remindersSentValue,
        formatNumber(sent)
    );

    setText(
        el.remindersSentDetail,
        `Successfully processed ${
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
            : "No reminder run recorded yet"
    );
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
    if (
        dashboardState.data
            .customers.length
    ) {
        return dashboardState.data
            .customers;
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

                phone:
                    bookingPhone(
                        booking
                    ),

                email:
                    booking.email ||
                    booking.customer_email ||
                    "",

                vehicles: [],
                bookings: []
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
                    registration
                });
            }

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
                    customer.phone,
                    customer.email,
                    ...vehicleRegistrations
                ]
                    .join(" ")
                    .toLowerCase();

                return (
                    !query ||
                    haystack.includes(query)
                );
            });

    if (!customers.length) {
        el.customerDirectory.innerHTML =
            createEmptyState(
                "👥",
                "No customers found",
                query
                    ? "Try a different customer or vehicle search."
                    : "Customer profiles will appear after bookings are loaded.",
                true
            );

        return;
    }

    el.customerDirectory.innerHTML =
        customers
            .slice(0, 12)
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

                const key =
                    customerKey({
                        name,
                        phone
                    });

                return `
                    <button
                        class="customer-directory-card"
                        type="button"
                        data-customer-key="${escapeAttribute(
                            key
                        )}"
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
                                ${vehicles.length}
                                vehicle${
                                    vehicles.length === 1
                                        ? ""
                                        : "s"
                                }
                                ·
                                ${bookings.length}
                                booking${
                                    bookings.length === 1
                                        ? ""
                                        : "s"
                                }
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

function renderSystemHealth() {
    const systems =
        dashboardState.data.systems;

    const overall =
        String(
            systems.overall ||
            "operational"
        ).toLowerCase();

    const healthy =
        isConnectedStatus(
            overall
        );

    if (el.overallSystemStatus) {
        el.overallSystemStatus.textContent =
            capitalise(overall);

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
            systems.vapi,
            "Ready for inbound calls"
        )
    );

    setText(
        el.calendarConnectionStatus,
        connectionText(
            systems.calendar,
            "Booking calendar connected"
        )
    );

    setText(
        el.dvlaConnectionStatus,
        connectionText(
            systems.dvla,
            "Vehicle lookup available"
        )
    );

    setText(
        el.backendConnectionStatus,
        connectionText(
            systems.backend,
            "Flask service online"
        )
    );

    setText(
        el.sidebarStatusText,
        healthy
            ? "Garage AI online"
            : "Garage AI needs attention"
    );

    setText(
        el.sidebarStatusDetail,
        healthy
            ? "Voice, calendar and reminder services are operational."
            : "One or more dashboard services reported an issue."
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
        Array.isArray(customer.vehicles)
            ? customer.vehicles
            : [];

    const bookings =
        Array.isArray(customer.bookings)
            ? customer.bookings
            : [];

    setText(
        el.customerDrawerTitle,
        name
    );

    if (el.customerDrawerBody) {
        el.customerDrawerBody.innerHTML = `
            <div class="drawer-profile-header">
                <div class="drawer-profile-avatar">
                    ${getCustomerInitials(name)}
                </div>

                <div>
                    <h3>
                        ${escapeHtml(name)}
                    </h3>

                    <p>
                        ${escapeHtml(phone)}
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
                    "Bookings",
                    formatNumber(
                        bookings.length
                    )
                )}
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Vehicles
                    </h4>
                </div>

                ${
                    vehicles.length
                        ? vehicles
                            .map((vehicle) => {
                                const registration =
                                    bookingRegistration(
                                        vehicle
                                    );

                                const vehicleName =
                                    vehicle.vehicle_name ||
                                    vehicle.make_model ||
                                    [
                                        vehicle.make,
                                        vehicle.model
                                    ]
                                        .filter(Boolean)
                                        .join(" ") ||
                                    "Vehicle";

                                return `
                                    <button
                                        class="drawer-list-item"
                                        type="button"
                                        data-vehicle-reg="${escapeAttribute(
                                            registration
                                        )}"
                                    >
                                        <span>
                                            <strong>
                                                ${escapeHtml(
                                                    vehicleName
                                                )}
                                            </strong>

                                            <small>
                                                ${escapeHtml(
                                                    registration
                                                )}
                                            </small>
                                        </span>

                                        <span>
                                            ›
                                        </span>
                                    </button>
                                `;
                            })
                            .join("")
                        : createEmptyState(
                            "🚗",
                            "No vehicles recorded",
                            "Vehicle information will appear after a DVLA lookup.",
                            true
                        )
                }
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Booking history
                    </h4>
                </div>

                ${
                    bookings.length
                        ? bookings
                            .slice(0, 8)
                            .map((booking) => {
                                const date =
                                    parseDate(
                                        bookingDateValue(
                                            booking
                                        )
                                    );

                                return `
                                    <div class="drawer-list-item static">
                                        <span>
                                            <strong>
                                                ${escapeHtml(
                                                    bookingService(
                                                        booking
                                                    )
                                                )}
                                            </strong>

                                            <small>
                                                ${
                                                    date
                                                        ? escapeHtml(
                                                            formatAppointmentDate(
                                                                date
                                                            )
                                                        )
                                                        : "Date unavailable"
                                                }
                                            </small>
                                        </span>

                                        <span class="status-badge ${getStatusClass(
                                            bookingStatus(
                                                booking
                                            )
                                        )}">
                                            ${escapeHtml(
                                                capitalise(
                                                    bookingStatus(
                                                        booking
                                                    )
                                                )
                                            )}
                                        </span>
                                    </div>
                                `;
                            })
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
            .trim()
            .toUpperCase();

    for (
        const customer of getCustomerRecords()
    ) {
        const vehicles =
            Array.isArray(customer.vehicles)
                ? customer.vehicles
                : [];

        const vehicle =
            vehicles.find(
                (item) =>
                    bookingRegistration(item)
                        .toUpperCase() ===
                    normalisedRegistration
            );

        if (vehicle) {
            return {
                ...vehicle,
                customer_name:
                    customer.name ||
                    customer.customer_name,
                customer_phone:
                    customer.phone ||
                    customer.customer_phone
            };
        }
    }

    return dashboardState.data
        .upcoming_appointments
        .find(
            (booking) =>
                bookingRegistration(booking)
                    .toUpperCase() ===
                normalisedRegistration
        );
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

    const colour =
        vehicle.colour ||
        vehicle.color ||
        "Unknown";

    const year =
        vehicle.year ||
        vehicle.manufacture_year ||
        "Unknown";

    const fuel =
        vehicle.fuel_type ||
        vehicle.fuel ||
        "Unknown";

    const motStatus =
        vehicle.mot_status ||
        vehicle.motStatus ||
        "Not loaded";

    const customer =
        vehicle.customer_name ||
        vehicle.name ||
        "Customer";

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
                            `${make} ${model}`
                        )}
                    </h3>

                    <p>
                        Owned by
                        ${escapeHtml(customer)}
                    </p>
                </div>
            </div>

            <div class="drawer-detail-grid">
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
            </div>

            <div class="drawer-section">
                <div class="drawer-section-header">
                    <h4>
                        Vehicle record
                    </h4>
                </div>

                <div class="drawer-note">
                    Vehicle information is supplied from
                    the booking and DVLA lookup data currently
                    available to the dashboard.
                </div>
            </div>
        `;
    }

    openDrawer(
        el.vehicleDrawer
    );
}

function openReminderDrawer() {
    const reminders =
        dashboardState.data.reminders;

    const queue =
        Array.isArray(reminders.queue)
            ? reminders.queue
            : [];

    setText(
        el.reminderCentreWaiting,
        formatNumber(
            reminders.waiting ??
            reminders.due
        )
    );

    setText(
        el.reminderCentreSent,
        formatNumber(
            reminders.sent_this_month ??
            reminders.sent
        )
    );

    setText(
        el.reminderCentreFailed,
        formatNumber(
            reminders.failed
        )
    );

    if (el.reminderQueueList) {
        el.reminderQueueList.innerHTML =
            queue.length
                ? queue
                    .slice(0, 12)
                    .map((reminder) => {
                        const customer =
                            reminder.customer_name ||
                            reminder.name ||
                            "Customer";

                        const service =
                            reminder.service ||
                            reminder.service_name ||
                            "Garage appointment";

                        const date =
                            parseDate(
                                reminder.send_at ||
                                reminder.datetime ||
                                reminder.date
                            );

                        const status =
                            String(
                                reminder.status ||
                                "pending"
                            ).toLowerCase();

                        return `
                            <div class="reminder-queue-item">
                                <div class="reminder-queue-icon">
                                    🔔
                                </div>

                                <div class="reminder-queue-copy">
                                    <strong>
                                        ${escapeHtml(
                                            customer
                                        )}
                                    </strong>

                                    <span>
                                        ${escapeHtml(
                                            service
                                        )}
                                    </span>

                                    <small>
                                        ${
                                            date
                                                ? escapeHtml(
                                                    formatAppointmentDate(
                                                        date
                                                    )
                                                )
                                                : "Scheduled reminder"
                                        }
                                    </small>
                                </div>

                                <span class="status-badge ${getStatusClass(
                                    status
                                )}">
                                    ${escapeHtml(
                                        capitalise(status)
                                    )}
                                </span>
                            </div>
                        `;
                    })
                    .join("")
                : createEmptyState(
                    "🔔",
                    "Reminder queue is clear",
                    "Upcoming reminders will appear here.",
                    true
                );
    }

    openDrawer(
        el.reminderDrawer
    );
}

function openDrawer(drawer) {
    closeAllDrawers();

    drawer?.classList.add("open");
    drawer?.setAttribute(
        "aria-hidden",
        "false"
    );

    el.drawerOverlay?.classList.add(
        "visible"
    );

    document.body.classList.add(
        "drawer-open"
    );
}

function closeAllDrawers() {
    [
        el.customerDrawer,
        el.vehicleDrawer,
        el.reminderDrawer
    ].forEach((drawer) => {
        drawer?.classList.remove("open");
        drawer?.setAttribute(
            "aria-hidden",
            "true"
        );
    });

    el.drawerOverlay?.classList.remove(
        "visible"
    );

    document.body.classList.remove(
        "drawer-open"
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