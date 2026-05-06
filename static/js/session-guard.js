(function () {
    var DATE_KEY = 'page_load_date';

    function todayStr() {
        var d = new Date();
        return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate();
    }

    function checkDayChanged() {
        var saved = localStorage.getItem(DATE_KEY);
        if (saved && saved !== todayStr()) {
            localStorage.removeItem(DATE_KEY);
            location.replace('/');
        }
    }

    // Record the date this page was loaded
    localStorage.setItem(DATE_KEY, todayStr());

    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) checkDayChanged();
    });

    // Handles tablets restoring from bfcache
    window.addEventListener('pageshow', function (e) {
        if (e.persisted) checkDayChanged();
    });
})();
