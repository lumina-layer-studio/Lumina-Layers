() => {
    setTimeout(() => {
        const trigger = document.querySelector('#color-rec-trigger');
        if (trigger) {
            const recommended = parseInt(trigger.dataset.recommended) || 0;
            const maxSafe = parseInt(trigger.dataset.maxsafe) || 0;
            if (recommended > 0 && typeof window.showColorRecommendationToast === 'function') {
                const lang = document.documentElement.lang || 'zh';
                let msg;
                if (lang === 'en') {
                    msg = '💡 Color detail set to <b>' + recommended + '</b> (max safe: ' + maxSafe + ')';
                } else {
                    msg = '💡 色彩细节已设置为 <b>' + recommended + '</b>（最大安全值: ' + maxSafe + '）';
                }
                window.showColorRecommendationToast(msg);
            }
            trigger.remove();
        }
    }, 100);
}
