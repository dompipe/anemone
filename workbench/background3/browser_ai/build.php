<?php declare(strict_types=1);

$here = __DIR__;
$repoRoot = dirname(__DIR__, 3);
$candidates = array_values(array_filter([
    getenv('JX_ROOT') ?: null,
    dirname(__DIR__, 4) . '/jx',
    $repoRoot . '/vendor/jx',
]));

$jxRoot = null;
foreach ($candidates as $candidate) {
    if (is_file($candidate . '/pasm-lang.php')) {
        $jxRoot = realpath($candidate) ?: $candidate;
        break;
    }
}
if ($jxRoot === null) {
    fwrite(STDERR, "Cannot find JX. Set JX_ROOT=/path/to/dompipe/jx or place jx beside anemone.\n");
    exit(2);
}

require_once $jxRoot . '/pasm-lang.php';

use pasm\lang\Compiler;

$pages = [
    'home' => 'pages/home.jx',
    'explore' => 'pages/explore.jx',
    'ask' => 'pages/ask.jx',
    'compare' => 'pages/compare.jx',
];

$build = $here . '/build';
$browser = $build . '/browser';
$runtime = $build . '/runtime';
@mkdir($browser, 0777, true);
@mkdir($runtime, 0777, true);

$compiler = new Compiler(true, false);
$manifest = [];
foreach ($pages as $id => $relative) {
    $sourcePath = $here . '/' . $relative;
    $source = file_get_contents($sourcePath);
    if ($source === false) {
        throw new RuntimeException("Cannot read {$relative}");
    }
    $pasm = $compiler->compile($source);
    $out = $browser . '/' . $id . '.pasm';
    file_put_contents($out, $pasm);
    $manifest[$id] = [
        'source' => $relative,
        'browser' => 'build/browser/' . $id . '.pasm',
    ];
}

$vmSource = $jxRoot . '/pasl/browser/pasl-vm.js';
if (!is_file($vmSource)) {
    throw new RuntimeException("JX browser VM not found at {$vmSource}");
}
copy($vmSource, $runtime . '/pasl-vm.js');

file_put_contents(
    $build . '/manifest.json',
    json_encode($manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n"
);

echo "anemone-ai: compiled 4 canonical JX leaves for browser mode\n";
echo "anemone-ai: copied JX PASM browser VM\n";
