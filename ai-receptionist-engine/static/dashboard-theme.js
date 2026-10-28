(function () {
    "use strict";

    var KEY = "trimtech-dashboard-theme";
    var root = document.documentElement;
    var media = window.matchMedia
        ? window.matchMedia("(prefers-color-scheme: dark)")
        : null;

    function saved() {
        try {
            var value = window.localStorage.getItem(KEY);
            return value === "dark" || value === "light" ? value : "";
        } catch (error) {
            return "";
        }
    }

    function current() {
        return saved() || (media && media.matches ? "dark" : "light");
    }

    function apply(theme) {
        root.setAttribute("data-theme", theme);

        var meta = document.querySelector('meta[name="theme-color"]');

        if (meta) {
            meta.setAttribute(
                "content",
                theme === "dark" ? "#0b1220" : "#f4f7fb"
            );
        }

        var button = document.getElementById("themeToggleButton");

        if (button) {
            button.setAttribute("aria-pressed", String(theme === "dark"));
        }
    }

    apply(current());

    document.addEventListener("DOMContentLoaded", function () {
        apply(current());

        var button = document.getElementById("themeToggleButton");

        if (!button) {
            return;
        }

        button.addEventListener("click", function () {
            var next =
                root.getAttribute("data-theme") === "dark" ? "light" : "dark";

            try {
                window.localStorage.setItem(KEY, next);
            } catch (error) {
                /* Preference is simply not remembered. */
            }

            apply(next);
        });
    });

    if (media && media.addEventListener) {
        media.addEventListener("change", function () {
            if (!saved()) {
                apply(current());
            }
        });
    }
})();
