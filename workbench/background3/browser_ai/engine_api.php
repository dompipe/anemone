<?php declare(strict_types=1);

function anemone_engine_event(string $type, array $data = []): void {
    echo json_encode(['type' => $type] + $data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n";
    @flush();
}

function anemone_engine_stream_start(): void {
    @ini_set('zlib.output_compression', '0');
    @ini_set('output_buffering', '0');
    @set_time_limit(75);
    while (ob_get_level() > 0) @ob_end_flush();
    ob_implicit_flush(true);
    header('Content-Type: application/x-ndjson; charset=utf-8');
    header('Cache-Control: no-cache, no-store');
    header('X-Accel-Buffering: no');
}

function anemone_engine_chunks(string $text): array {
    $text = trim($text);
    if ($text === '') return [];
    $paragraphs = preg_split('/\n{2,}/u', $text, -1, PREG_SPLIT_NO_EMPTY) ?: [$text];
    $chunks = [];
    foreach ($paragraphs as $paragraph) {
        $sentences = preg_split('/(?<=[.!?])\s+/u', trim($paragraph), -1, PREG_SPLIT_NO_EMPTY) ?: [trim($paragraph)];
        foreach ($sentences as $sentence) {
            if ($sentence !== '') $chunks[] = rtrim($sentence) . ' ';
        }
        if ($chunks) $chunks[count($chunks) - 1] = rtrim($chunks[count($chunks) - 1]) . "\n\n";
    }
    return $chunks;
}

function handle_anemone_engine_ask(): never {
    $raw = file_get_contents('php://input') ?: '';
    $body = json_decode($raw, true);
    if (!is_array($body)) $body = [];
    $prompt = trim((string)($body['prompt'] ?? ''));

    anemone_engine_stream_start();
    if ($prompt === '') {
        anemone_engine_event('chunk', ['text' => 'Ask me a question.']);
        anemone_engine_event('done', ['engine' => 'anemone']);
        exit;
    }

    anemone_engine_event('status', ['label' => 'Querying full Anemone knowledge engine']);

    $python = trim((string)(getenv('ANEMONE_PYTHON') ?: 'python3'));
    $bridge = __DIR__ . '/engine_bridge.py';
    $repoRoot = dirname(__DIR__, 3);
    $spec = [
        0 => ['pipe', 'r'],
        1 => ['pipe', 'w'],
        2 => ['pipe', 'w'],
    ];

    $proc = @proc_open([$python, $bridge], $spec, $pipes, $repoRoot);
    if (!is_resource($proc)) {
        anemone_engine_event('chunk', ['text' => "The Anemone Python engine could not start. Set ANEMONE_PYTHON to your Python executable if python3 is not on PATH."]);
        anemone_engine_event('done', ['engine' => 'engine-unavailable']);
        exit;
    }

    fwrite($pipes[0], json_encode(['prompt' => $prompt], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
    fclose($pipes[0]);
    stream_set_blocking($pipes[1], false);
    stream_set_blocking($pipes[2], false);

    $stdout = '';
    $stderr = '';
    $deadline = microtime(true) + 60.0;
    $timedOut = false;
    while (true) {
        $stdout .= stream_get_contents($pipes[1]) ?: '';
        $stderr .= stream_get_contents($pipes[2]) ?: '';
        $status = proc_get_status($proc);
        if (!$status['running']) break;
        if (microtime(true) >= $deadline) {
            $timedOut = true;
            proc_terminate($proc, 15);
            break;
        }
        usleep(20000);
    }
    $stdout .= stream_get_contents($pipes[1]) ?: '';
    $stderr .= stream_get_contents($pipes[2]) ?: '';
    fclose($pipes[1]);
    fclose($pipes[2]);
    @proc_close($proc);

    if ($timedOut) {
        anemone_engine_event('chunk', ['text' => 'The Anemone knowledge engine exceeded the 60-second browser request limit.']);
        anemone_engine_event('done', ['engine' => 'engine-timeout']);
        exit;
    }

    $result = json_decode(trim($stdout), true);
    if (!is_array($result) || !($result['ok'] ?? false)) {
        $detail = is_array($result) ? (string)($result['error'] ?? 'unknown engine error') : trim($stderr ?: $stdout);
        if ($detail === '') $detail = 'unknown engine error';
        anemone_engine_event('chunk', ['text' => 'The full Anemone engine failed: ' . $detail]);
        anemone_engine_event('done', ['engine' => 'engine-error']);
        exit;
    }

    $reply = trim((string)($result['reply'] ?? ''));
    if ($reply === '') $reply = 'Anemone returned no text for that question.';
    anemone_engine_event('status', ['label' => 'Composing answer from Anemone corpus']);
    foreach (anemone_engine_chunks($reply) as $chunk) {
        anemone_engine_event('chunk', ['text' => $chunk]);
    }
    anemone_engine_event('engine', [
        'name' => (string)($result['engine'] ?? 'eng1neer.respond_subject_specific'),
    ]);
    anemone_engine_event('status', ['label' => 'Ready']);
    anemone_engine_event('done', ['engine' => 'anemone-full']);
    exit;
}
