<?php declare(strict_types=1);

$op = (string)($_GET['op'] ?? 'bootstrap');
if ($op === 'ask') {
    require __DIR__ . '/engine_api.php';
    handle_anemone_engine_ask();
}

require __DIR__ . '/api_core.php';
