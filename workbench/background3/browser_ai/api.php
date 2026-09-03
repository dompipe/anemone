<?php declare(strict_types=1);

$op = (string)($_GET['op'] ?? 'bootstrap');
if ($op === 'ask') {
    require __DIR__ . '/engine_api.php';
    handle_anemone_engine_ask();
}

$storeRoot = getenv('ANEMONE_TAXONOMY_STORE')
    ?: dirname(__DIR__) . '/sqlite_taxonomy/anemone_taxonomy.mmap';
if (is_file($storeRoot . '/store.json') && is_file($storeRoot . '/catalog.sqlite3')) {
    require __DIR__ . '/mmap_api_core.php';
    exit;
}

// Compatibility fallback for an older monolithic taxonomy database or demo mode.
require __DIR__ . '/api_core.php';
