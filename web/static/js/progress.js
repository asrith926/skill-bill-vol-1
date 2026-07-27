// WebSocket client for pipeline progress

(function() {
    const ws = new WebSocket(`ws://${window.location.host}/ws/progress`);
    const stages = document.querySelectorAll('.stage');
    const logPanel = document.getElementById('log-panel');
    const completion = document.getElementById('completion');

    function addLog(message) {
        const line = document.createElement('div');
        line.className = 'log-line';
        line.textContent = `> ${message}`;
        logPanel.appendChild(line);
        logPanel.scrollTop = logPanel.scrollHeight;
    }

    function setStageActive(stageName) {
        stages.forEach(el => {
            if (el.dataset.stage === stageName) {
                el.classList.remove('stage--pending');
                el.classList.add('stage--active');
            }
        });
    }

    function setStageComplete(stageName, data) {
        stages.forEach(el => {
            if (el.dataset.stage === stageName) {
                el.classList.remove('stage--active');
                el.classList.add('stage--complete');
                if (data) {
                    const detail = el.querySelector('.stage-detail');
                    if (detail) {
                        detail.textContent = formatStageData(stageName, data);
                    }
                }
            }
        });
    }

    function formatStageData(stage, data) {
        switch(stage) {
            case 'discovery': return `${data.title} (${data.video_count} videos)`;
            case 'transcripts': return `${data.found}/${data.total} found`;
            case 'download': return `${data.downloaded}/${data.total} downloaded`;
            case 'screenshot_planning': return `${data.total_screenshots} screenshots planned`;
            case 'capture': return `${data.screenshots_kept} screenshots captured`;
            case 'generation': return 'Markdown files generated';
            case 'refinement': return 'Lessons refined';
            default: return '';
        }
    }

    function showCompletion(event) {
        const title = document.getElementById('completion-title');
        const viewLink = document.getElementById('view-link');
        const downloadLink = document.getElementById('download-link');

        title.textContent = event.course_title;
        viewLink.href = `/course/${event.course_slug}`;
        downloadLink.href = `/download/${event.course_slug}`;

        completion.classList.add('completion--visible');

        // Hide the spinner
        const spinner = document.querySelector('.spinner');
        if (spinner) spinner.style.display = 'none';
    }

    ws.onmessage = function(e) {
        const event = JSON.parse(e.data);

        switch(event.type) {
            case 'stage_start':
                setStageActive(event.stage);
                addLog(`Starting: ${event.stage}`);
                break;
            case 'stage_complete':
                setStageComplete(event.stage, event.data);
                addLog(`Complete: ${event.stage}`);
                break;
            case 'video_progress':
                addLog(`[${event.stage}] ${event.current}/${event.total}: ${event.title}`);
                break;
            case 'log':
                addLog(event.message);
                break;
            case 'pipeline_complete':
                addLog('Pipeline complete!');
                showCompletion(event);
                break;
            case 'error':
                addLog(`ERROR: ${event.message}`);
                if (event.fatal) {
                    const spinner = document.querySelector('.spinner');
                    if (spinner) spinner.style.display = 'none';
                }
                break;
        }
    };

    ws.onerror = function() {
        addLog('WebSocket connection error');
    };
})();
