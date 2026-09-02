<?php declare(strict_types=1);

const ANEMONE_MAX_PROMPT = 12000;
const ANEMONE_MAX_RESULTS = 50;

$dbPath = getenv('ANEMONE_TAXONOMY_DB') ?: dirname(__DIR__) . '/sqlite_taxonomy/anemone_taxonomy.sqlite3';

function db_open(string $path): ?PDO {
    if (!is_file($path)) return null;
    try {
        $pdo = new PDO('sqlite:' . $path, null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
        $pdo->exec('PRAGMA query_only=ON');
        $pdo->exec('PRAGMA busy_timeout=2500');
        return $pdo;
    } catch (Throwable $e) {
        return null;
    }
}

function json_out(mixed $payload, int $status = 200): never {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function read_body(): array {
    $raw = file_get_contents('php://input') ?: '';
    if ($raw === '') return [];
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

function stream_start(): void {
    @ini_set('zlib.output_compression', '0');
    @ini_set('output_buffering', '0');
    while (ob_get_level() > 0) @ob_end_flush();
    ob_implicit_flush(true);
    header('Content-Type: application/x-ndjson; charset=utf-8');
    header('Cache-Control: no-cache, no-store');
    header('X-Accel-Buffering: no');
}

function stream_event(string $type, array $data = []): void {
    echo json_encode(['type' => $type] + $data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n";
    @flush();
}

function demo_taxa(): array {
    return [
        -1 => ['taxon_id'=>-1,'rank'=>'kingdom','canonical_name'=>'Animalia','common_name'=>'animals','origin_kind'=>'demo','source'=>'demo'],
        -2 => ['taxon_id'=>-2,'rank'=>'kingdom','canonical_name'=>'Plantae','common_name'=>'plants','origin_kind'=>'demo','source'=>'demo'],
        -3 => ['taxon_id'=>-3,'rank'=>'kingdom','canonical_name'=>'Fungi','common_name'=>'fungi','origin_kind'=>'demo','source'=>'demo'],
        -11 => ['taxon_id'=>-11,'rank'=>'phylum','canonical_name'=>'Chordata','common_name'=>'chordates','origin_kind'=>'demo','source'=>'demo'],
        -12 => ['taxon_id'=>-12,'rank'=>'class','canonical_name'=>'Mammalia','common_name'=>'mammals','origin_kind'=>'demo','source'=>'demo'],
        -13 => ['taxon_id'=>-13,'rank'=>'order','canonical_name'=>'Carnivora','common_name'=>'carnivorans','origin_kind'=>'demo','source'=>'demo'],
        -14 => ['taxon_id'=>-14,'rank'=>'family','canonical_name'=>'Canidae','common_name'=>'canids','origin_kind'=>'demo','source'=>'demo'],
        -15 => ['taxon_id'=>-15,'rank'=>'genus','canonical_name'=>'Canis','common_name'=>'canis','origin_kind'=>'demo','source'=>'demo'],
        -16 => ['taxon_id'=>-16,'rank'=>'species','canonical_name'=>'Canis lupus','common_name'=>'gray wolf','origin_kind'=>'demo','source'=>'demo'],
    ];
}

function demo_parent(): array {
    return [-11=>-1,-12=>-11,-13=>-12,-14=>-13,-15=>-14,-16=>-15];
}

function demo_descriptors(int $id): array {
    $rows = [
        -1 => [['descriptor_text'=>'multicellular body','kind'=>'trait','state'=>'present','from_rank'=>'kingdom','from_name'=>'Animalia','depth'=>0]],
        -11 => [['descriptor_text'=>'dorsal nerve cord','kind'=>'phenotype','state'=>'present','from_rank'=>'phylum','from_name'=>'Chordata','depth'=>0]],
        -12 => [
            ['descriptor_text'=>'hair covered','kind'=>'phenotype','state'=>'present','from_rank'=>'class','from_name'=>'Mammalia','depth'=>0],
            ['descriptor_text'=>'milk producing','kind'=>'trait','state'=>'present','from_rank'=>'class','from_name'=>'Mammalia','depth'=>0],
            ['descriptor_text'=>'warm blooded','kind'=>'trait','state'=>'present','from_rank'=>'class','from_name'=>'Mammalia','depth'=>0],
        ],
        -14 => [
            ['descriptor_text'=>'elongated muzzle','kind'=>'phenotype','state'=>'present','from_rank'=>'family','from_name'=>'Canidae','depth'=>0],
            ['descriptor_text'=>'retractile claws','kind'=>'phenotype','state'=>'absent','from_rank'=>'family','from_name'=>'Canidae','depth'=>0],
        ],
        -16 => [
            ['descriptor_text'=>'pack hunting','kind'=>'trait','state'=>'variable','from_rank'=>'species','from_name'=>'Canis lupus','depth'=>0],
            ['descriptor_text'=>'dense winter coat','kind'=>'phenotype','state'=>'present','from_rank'=>'species','from_name'=>'Canis lupus','depth'=>0],
        ],
    ];
    $parents = demo_parent();
    $chain = [];
    for ($n=$id, $depth=0; isset(demo_taxa()[$n]); $depth++) {
        $chain[] = [$n,$depth];
        if (!isset($parents[$n])) break;
        $n = $parents[$n];
    }
    $resolved = [];
    foreach ($chain as [$node,$depth]) {
        foreach ($rows[$node] ?? [] as $r) {
            $key = $r['kind'] . ':' . $r['descriptor_text'];
            if (isset($resolved[$key])) continue;
            $r['depth'] = $depth;
            $resolved[$key] = $r;
        }
    }
    return array_values($resolved);
}

function db_taxon(PDO $db, int $id): ?array {
    $s = $db->prepare('SELECT * FROM TAXON WHERE taxon_id=?');
    $s->execute([$id]);
    $row = $s->fetch();
    return $row ?: null;
}

function db_lineage(PDO $db, int $id): array {
    $sql = <<<'SQL'
WITH RECURSIVE ancestry(taxon_id, depth) AS (
  SELECT :id, 0
  UNION ALL
  SELECT e.parent_id, ancestry.depth + 1
  FROM ancestry JOIN TAXON_EDGE e ON e.child_id = ancestry.taxon_id
)
SELECT t.*, ancestry.depth
FROM ancestry JOIN TAXON t USING(taxon_id)
ORDER BY ancestry.depth DESC
SQL;
    $s = $db->prepare($sql);
    $s->execute([':id'=>$id]);
    return $s->fetchAll();
}

function db_children(PDO $db, int $id, int $limit = 25): array {
    $s = $db->prepare(
        'SELECT t.*, e.page_no, e.slot_no FROM TAXON_EDGE e JOIN TAXON t ON t.taxon_id=e.child_id WHERE e.parent_id=? ORDER BY e.page_no,e.slot_no LIMIT ?'
    );
    $s->bindValue(1, $id, PDO::PARAM_INT);
    $s->bindValue(2, min(max($limit,1),ANEMONE_MAX_RESULTS), PDO::PARAM_INT);
    $s->execute();
    return $s->fetchAll();
}

function db_effective_descriptors(PDO $db, int $id, int $limit = 250): array {
    $sql = <<<'SQL'
WITH RECURSIVE ancestry(taxon_id, depth) AS (
  SELECT :id, 0
  UNION ALL
  SELECT e.parent_id, ancestry.depth + 1
  FROM ancestry JOIN TAXON_EDGE e ON e.child_id = ancestry.taxon_id
), ranked AS (
  SELECT d.descriptor_text, td.kind, td.state, td.inheritable, td.confidence,
         td.source, td.source_ref, a.depth, t.rank AS from_rank,
         t.canonical_name AS from_name,
         ROW_NUMBER() OVER (
           PARTITION BY td.descriptor_id, td.kind ORDER BY a.depth ASC
         ) AS rn
  FROM ancestry a
  JOIN TAXON_DESCRIPTOR td ON td.taxon_id=a.taxon_id
  JOIN DESCRIPTOR d ON d.descriptor_id=td.descriptor_id
  JOIN TAXON t ON t.taxon_id=a.taxon_id
  WHERE a.depth=0 OR td.inheritable=1
)
SELECT * FROM ranked WHERE rn=1
ORDER BY kind,state,descriptor_text LIMIT :limit
SQL;
    $s = $db->prepare($sql);
    $s->bindValue(':id', $id, PDO::PARAM_INT);
    $s->bindValue(':limit', min(max($limit,1),1000), PDO::PARAM_INT);
    $s->execute();
    return $s->fetchAll();
}

function demo_lineage(int $id): array {
    $taxa = demo_taxa(); $parents = demo_parent(); $out=[]; $depth=0;
    for ($n=$id; isset($taxa[$n]); $depth++) {
        $r=$taxa[$n]; $r['depth']=$depth; array_unshift($out,$r);
        if (!isset($parents[$n])) break;
        $n=$parents[$n];
    }
    return $out;
}

function demo_children(int $id): array {
    $taxa=demo_taxa(); $parents=demo_parent(); $out=[];
    foreach ($parents as $child=>$parent) if ($parent===$id) $out[]=$taxa[$child];
    return $out;
}

function taxon_payload(?PDO $db, int $id): ?array {
    if ($db) {
        $taxon=db_taxon($db,$id); if (!$taxon) return null;
        return [
            'taxon'=>$taxon,
            'lineage'=>db_lineage($db,$id),
            'children'=>db_children($db,$id,25),
            'descriptors'=>db_effective_descriptors($db,$id),
        ];
    }
    $taxa=demo_taxa(); if (!isset($taxa[$id])) return null;
    return [
        'taxon'=>$taxa[$id],
        'lineage'=>demo_lineage($id),
        'children'=>demo_children($id),
        'descriptors'=>demo_descriptors($id),
    ];
}

function search_taxa(?PDO $db, string $q, int $limit = 20): array {
    $q=trim($q); if ($q==='') return [];
    if (!$db) {
        $needle=mb_strtolower($q); $out=[];
        foreach (demo_taxa() as $row) {
            $hay=mb_strtolower(($row['canonical_name']??'').' '.($row['common_name']??''));
            if (str_contains($hay,$needle)) $out[]=$row;
        }
        return array_slice($out,0,$limit);
    }
    $sql = <<<'SQL'
SELECT DISTINCT t.*
FROM TAXON t
LEFT JOIN TAXON_ALIAS a ON a.taxon_id=t.taxon_id
WHERE lower(t.canonical_name) LIKE :q
   OR lower(COALESCE(t.common_name,'')) LIKE :q
   OR lower(COALESCE(t.scientific_name,'')) LIKE :q
   OR lower(COALESCE(a.alias,'')) LIKE :q
ORDER BY CASE WHEN lower(t.canonical_name)=lower(:exact) THEN 0 ELSE 1 END,
         length(t.canonical_name), t.canonical_name
LIMIT :limit
SQL;
    $s=$db->prepare($sql);
    $s->bindValue(':q','%'.mb_strtolower($q).'%');
    $s->bindValue(':exact',$q);
    $s->bindValue(':limit',min(max($limit,1),ANEMONE_MAX_RESULTS),PDO::PARAM_INT);
    $s->execute(); return $s->fetchAll();
}

function prompt_taxon(?PDO $db, string $prompt, ?int $preferred = null): ?array {
    if ($preferred !== null) {
        $payload=taxon_payload($db,$preferred); if ($payload) return $payload;
    }
    if ($db) {
        $s=$db->prepare(
            'SELECT * FROM TAXON WHERE instr(lower(:prompt),lower(canonical_name))>0 ORDER BY length(canonical_name) DESC LIMIT 1'
        );
        $s->execute([':prompt'=>$prompt]);
        $row=$s->fetch();
        if ($row) return taxon_payload($db,(int)$row['taxon_id']);
    } else {
        $lower=mb_strtolower($prompt); $best=null;
        foreach (demo_taxa() as $row) {
            foreach ([$row['canonical_name']??'', $row['common_name']??''] as $name) {
                if ($name!=='' && str_contains($lower,mb_strtolower($name))) {
                    if ($best===null || strlen($name)>strlen($best[1])) $best=[(int)$row['taxon_id'],$name];
                }
            }
        }
        if ($best) return taxon_payload(null,$best[0]);
    }
    $words=preg_split('/[^A-Za-z0-9_-]+/u',$prompt,-1,PREG_SPLIT_NO_EMPTY) ?: [];
    usort($words,fn($a,$b)=>strlen($b)<=>strlen($a));
    foreach (array_slice($words,0,8) as $word) {
        if (strlen($word)<4) continue;
        $hits=search_taxa($db,$word,1);
        if ($hits) return taxon_payload($db,(int)$hits[0]['taxon_id']);
    }
    return null;
}

function states_for(array $descriptors): array {
    $out=['present'=>[],'absent'=>[],'variable'=>[]];
    foreach ($descriptors as $d) {
        $state=$d['state'] ?? 'present';
        if (isset($out[$state])) $out[$state][]=$d;
    }
    return $out;
}

function recognized_requested(?PDO $db, string $prompt, array $effective): array {
    $lower=mb_strtolower($prompt); $out=[];
    foreach ($effective as $d) {
        $text=mb_strtolower((string)$d['descriptor_text']);
        if ($text!=='' && str_contains($lower,$text)) $out[$text]=$d;
    }
    if ($db) {
        $s=$db->prepare('SELECT descriptor_text FROM DESCRIPTOR WHERE instr(lower(:prompt),descriptor_text)>0 ORDER BY length(descriptor_text) DESC LIMIT 20');
        $s->execute([':prompt'=>$prompt]);
        foreach ($s->fetchAll() as $r) {
            $t=$r['descriptor_text']; if (!isset($out[$t])) $out[$t]=['descriptor_text'=>$t,'state'=>'unknown','kind'=>'trait'];
        }
    }
    return array_values($out);
}

function stream_answer(?PDO $db, string $prompt, ?int $preferred): never {
    stream_start();
    stream_event('status',['label'=>'Searching taxonomy','engine'=>$db?'sqlite-live':'demo']);
    $payload=prompt_taxon($db,$prompt,$preferred);
    if (!$payload) {
        stream_event('status',['label'=>'Looking for close concepts']);
        $hits=search_taxa($db,$prompt,6);
        $names=array_map(fn($r)=>$r['canonical_name'],$hits);
        $answer=$names
            ? 'I did not resolve one taxon confidently. The closest indexed concepts are '.implode(', ',$names).'.'
            : 'I could not resolve that question to a taxon yet. Try a scientific name, common name, or a two-to-three-word descriptor.';
        foreach (preg_split('/(?<=[.!?])\s+/',$answer,-1,PREG_SPLIT_NO_EMPTY) as $chunk) stream_event('chunk',['text'=>$chunk.' ']);
        stream_event('done',['engine'=>$db?'taxonomy-live':'demo']);
        exit;
    }

    $taxon=$payload['taxon']; $lineage=$payload['lineage']; $descriptors=$payload['descriptors'];
    $states=states_for($descriptors); $requested=recognized_requested($db,$prompt,$descriptors);
    stream_event('context',[
        'taxon'=>$taxon,
        'lineage'=>$lineage,
        'children'=>$payload['children'],
    ]);
    stream_event('status',['label'=>'Resolving inherited traits']);

    $lineNames=array_map(fn($r)=>$r['canonical_name'],$lineage);
    $name=$taxon['canonical_name']; $rank=$taxon['rank'];
    $chunks=[];
    $chunks[]="{$name} is indexed as {$rank}. ";
    if (count($lineNames)>1) $chunks[]='Its current Anemone lineage is '.implode(' → ',$lineNames).'. ';

    if ($requested) {
        $p=[];$a=[];$v=[];$u=[];
        foreach ($requested as $d) {
            $text=$d['descriptor_text']; $state=$d['state']??'unknown';
            if ($state==='present') $p[]=$text; elseif ($state==='absent') $a[]=$text; elseif ($state==='variable') $v[]=$text; else $u[]=$text;
        }
        $parts=[];
        if ($p) $parts[]='present: '.implode(', ',$p);
        if ($a) $parts[]='absent: '.implode(', ',$a);
        if ($v) $parts[]='variable: '.implode(', ',$v);
        if ($u) $parts[]='not established: '.implode(', ',$u);
        if ($parts) $chunks[]='For the descriptors in your question, '.implode('; ',$parts).'. ';
    } else {
        $top=array_slice($states['present'],0,7);
        if ($top) $chunks[]='Some effective descriptors are '.implode(', ',array_map(fn($d)=>$d['descriptor_text'],$top)).'. ';
        if ($states['absent']) $chunks[]='It also has explicit absences such as '.implode(', ',array_map(fn($d)=>$d['descriptor_text'],array_slice($states['absent'],0,3))).'. ';
        if ($states['variable']) $chunks[]='Variable traits include '.implode(', ',array_map(fn($d)=>$d['descriptor_text'],array_slice($states['variable'],0,3))).'. ';
    }

    $childCount=count($payload['children']);
    if ($childCount) $chunks[]="I can descend into {$childCount} loaded child nodes from here, or compare this node against another descriptor set. ";
    else $chunks[]='This is currently a leaf in the loaded portion of the taxonomy. ';

    foreach ($chunks as $chunk) stream_event('chunk',['text'=>$chunk]);
    stream_event('evidence',[
        'descriptors'=>array_slice($descriptors,0,80),
        'requested'=>$requested,
        'origin_kind'=>$taxon['origin_kind'] ?? 'scientific',
        'source'=>$taxon['source'] ?? null,
        'source_ref'=>$taxon['source_ref'] ?? null,
    ]);
    stream_event('status',['label'=>'Ready']);
    stream_event('done',['engine'=>$db?'taxonomy-live':'demo','taxon_id'=>(int)$taxon['taxon_id']]);
    exit;
}

$db=db_open($dbPath);
$op=(string)($_GET['op'] ?? 'bootstrap');

if ($op==='bootstrap') {
    if ($db) {
        $kingdoms=$db->query("SELECT * FROM TAXON WHERE rank='kingdom' ORDER BY canonical_name LIMIT 100")->fetchAll();
        $taxa=(int)$db->query('SELECT COUNT(*) FROM TAXON')->fetchColumn();
        $desc=(int)$db->query('SELECT COUNT(*) FROM TAXON_DESCRIPTOR')->fetchColumn();
        $pageSize=(int)$db->query('PRAGMA page_size')->fetchColumn();
        $pageCount=(int)$db->query('PRAGMA page_count')->fetchColumn();
        $maxPages=(int)$db->query('PRAGMA max_page_count')->fetchColumn();
        json_out([
            'mode'=>'live','kingdoms'=>$kingdoms,
            'ranks'=>['kingdom','phylum','class','order','family','genus','species','type','name'],
            'stats'=>[
                'taxa'=>$taxa,'descriptor_assignments'=>$desc,
                'bytes'=>$pageSize*$pageCount,'max_bytes'=>$pageSize*$maxPages,
            ],
        ]);
    }
    $taxa=demo_taxa();
    json_out([
        'mode'=>'demo',
        'kingdoms'=>array_values(array_filter($taxa,fn($r)=>$r['rank']==='kingdom')),
        'ranks'=>['kingdom','phylum','class','order','family','genus','species','type','name'],
        'stats'=>['taxa'=>count($taxa),'descriptor_assignments'=>count(demo_descriptors(-16)),'bytes'=>0,'max_bytes'=>35*1024**3],
    ]);
}

if ($op==='taxon') {
    $id=(int)($_GET['taxon_id'] ?? 0); $payload=taxon_payload($db,$id);
    if (!$payload) json_out(['error'=>'taxon not found'],404);
    json_out($payload);
}

if ($op==='children') {
    $id=(int)($_GET['taxon_id'] ?? 0);
    json_out(['children'=>$db?db_children($db,$id,25):demo_children($id)]);
}

if ($op==='search') {
    $q=mb_substr((string)($_GET['q'] ?? ''),0,300);
    json_out(['results'=>search_taxa($db,$q,25)]);
}

if ($op==='compare') {
    $body=read_body(); $id=(int)($body['taxon_id']??0); $requested=$body['descriptors']??[];
    if (!is_array($requested)) $requested=[];
    $payload=taxon_payload($db,$id); if (!$payload) json_out(['error'=>'taxon not found'],404);
    $effective=[]; foreach ($payload['descriptors'] as $d) $effective[mb_strtolower($d['descriptor_text'])]=$d;
    $result=['present'=>[],'absent'=>[],'variable'=>[],'unknown'=>[]];
    foreach (array_slice($requested,0,30) as $raw) {
        $text=mb_strtolower(trim((string)$raw)); if ($text==='') continue;
        $d=$effective[$text]??null; $state=$d['state']??'unknown';
        $result[$state][]=['descriptor'=>$text,'evidence'=>$d];
    }
    json_out(['taxon'=>$payload['taxon'],'result'=>$result]);
}

if ($op==='ask') {
    $body=read_body();
    $prompt=trim((string)($body['prompt']??''));
    if ($prompt==='') json_out(['error'=>'prompt required'],400);
    if (mb_strlen($prompt)>ANEMONE_MAX_PROMPT) $prompt=mb_substr($prompt,0,ANEMONE_MAX_PROMPT);
    $preferred=isset($body['taxon_id']) ? (int)$body['taxon_id'] : null;
    stream_answer($db,$prompt,$preferred);
}

json_out(['error'=>'unknown operation'],404);
