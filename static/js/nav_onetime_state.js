(function () {
    function apply() {
        if (!sessionStorage.getItem("fts_onetime_share_completed")) {
            return;
        }
        var el = document.querySelector(".nav-onetime-link");
        if (el) {
            el.classList.add("nav-onetime-used");
        }
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", apply);
    } else {
        apply();
    }
})();
