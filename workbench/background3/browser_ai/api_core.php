<?php declare(strict_types=1);

const ANEMONE_MAX_PROMPT = 12000;
const ANEMONE_MAX_RESULTS = 50;

$taxonomyPath = getenv('ANEMONE_TAXONOMY_DB') ?: dirname(__DIR__) . '/sqlite_taxonomy/anemone_taxonomy.sqlite3';
$encyclopediaPath = getenv('ANEMONE_ENCYCLOPEDIA_DB') ?: dirname(__DIR__) . '/sqlite_taxonomy/cache/encyclopedia_index.sqlite3';

function open_sqlite(string $path): ?PDO {
    if (!is_file($path)) return null;
    try {
        $db = new PDO('sqlite:' . $path, null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
        $db->exec('PRAGMA query_only=ON');
        $db->exec('PRAGMA busy_timeout=2500');
        return $db;
    } catch (Throwable) {
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
    $data = $raw === '' ? [] : json_decode($raw, true);
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
    echo json_encode(['type'=>$type] + $data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n";
    @flush();
}

function demo_taxa(): array {
    return [
        -1  => ['taxon_id'=>-1,'rank'=>'kingdom','canonical_name'=>'Animalia','common_name'=>'animals','origin_kind'=>'demo','source'=>'demo'],
        -2  => ['taxon_id'=>-2,'rank'=>'kingdom','canonical_name'=>'Plantae','common_name'=>'plants','origin_kind'=>'demo','source'=>'demo'],
        -3  => ['taxon_id'=>-3,'rank'=>'kingdom','canonical_name'=>'Fungi','common_name'=>'fungi','origin_kind'=>'demo','source'=>'demo'],
        -11 => ['taxon_id'=>-11,'rank'=>'phylum','canonical_name'=>'Chordata','common_name'=>'chordates','origin_kind'=>'demo','source'=>'demo'],
        -12 => ['taxon_id'=>-12,'rank'=>'class','canonical_name'=>'Mammalia','common_name'=>'mammals','origin_kind'=>'demo','source'=>'demo'],
        -13 => ['taxon_id'=>-13,'rank'=>'order','canonical_name'=>'Carnivora','common_name'=>'carnivorans','origin_kind'=>'demo','source'=>'demo'],
        -14 => ['taxon_id'=>-14,'rank'=>'family','canonical_name'=>'Canidae','common_name'=>'canids','origin_kind'=>'demo','source'=>'demo'],
        -15 => ['taxon_id'=>-15,'rank'=>'genus','canonical_name'=>'Canis','common_name'=>'canis','origin_kind'=>'demo','source'=>'demo'],
        -16 => ['taxon_id'=>-16,'rank'=>'species','canonical_name'=>'Canis lupus','common_name'=>'gray wolf','origin_kind'=>'demo','source'=>'demo'],
        -17 => ['taxon_id'=>-17,'rank'=>'class','canonical_name'=>'Aves','common_name'=>'birds','origin_kind'=>'demo','source'=>'demo'],
    ];
}

function demo_parent(): array {
    return [-11=>-1,-12=>-11,-13=>-12,-14=>-13,-15=>-14,-16=>-15,-17=>-11];
}

function demo_local_descriptors(): array {
    return [
        -1  => [['descriptor_text'=>'multicellular body','kind'=>'trait','state'=>'present']],
        -11 => [['descriptor_text'=>'dorsal nerve cord','kind'=>'phenotype','state'=>'present']],
        -12 => [
            ['descriptor_text'=>'hair covered','kind'=>'phenotype','state'=>'present'],
            ['descriptor_text'=>'milk producing','kind'=>'trait','state'=>'present'],
            ['descriptor_text'=>'warm blooded','kind'=>'trait','state'=>'present'],
        ],
        -14 => [
            ['descriptor_text'=>'elongated muzzle','kind'=>'phenotype','state'=>'present'],
            ['descriptor_text'=>'retractile claws','kind'=>'phenotype','state'=>'absent'],
        ],
        -16 => [
            ['descriptor_text'=>'pack hunting','kind'=>'trait','state'=>'variable'],
            ['descriptor_text'=>'dense winter coat','kind'=>'phenotype','state'=>'present'],
        ],
        -17 => [
            ['descriptor_text'=>'feather covered','kind'=>'phenotype','state'=>'present'],
            ['descriptor_text'=>'beaked mouth','kind'=>'phenotype','state'=>'present'],
            ['descriptor_text'=>'egg laying','kind'=>'trait','state'=>'present'],
            ['descriptor_text'=>'powered flight','kind'=>'trait','state'=>'variable'],
        ],
    ];
}

function demo_lineage(int $id): array {
    $taxa=demo_taxa(); $parents=demo_parent(); $out=[]; $depth=0;
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

function demo_descriptors(int $id): array {
    $taxa=demo_taxa(); $parents=demo_parent(); $local=demo_local_descriptors(); $resolved=[];
    for ($n=$id,$depth=0; isset($taxa[$n]); $depth++) {
        foreach ($local[$n] ?? [] as $d) {
            $key=$d['kind'].':'.$d['descriptor_text'];
            if (isset($resolved[$key])) continue;
            $d['from_rank']=$taxa[$n]['rank'];
            $d['from_name']=$taxa[$n]['canonical_name'];
            $d['depth']=$depth;
            $resolved[$key]=$d;
        }
        if (!isset($parents[$n])) break;
        $n=$parents[$n];
    }
    return array_values($resolved);
}

function db_taxon(PDO $db, int $id): ?array {
    $s=$db->prepare('SELECT * FROM TAXON WHERE taxon_id=?'); $s->execute([$id]);
    return ($r=$s->fetch()) ? $r : null;
}

function db_lineage(PDO $db, int $id): array {
    $sql="WITH RECURSIVE ancestry(taxon_id,depth) AS (SELECT :id,0 UNION ALL SELECT e.parent_id,ancestry.depth+1 FROM ancestry JOIN TAXON_EDGE e ON e.child_id=ancestry.taxon_id) SELECT t.*,ancestry.depth FROM ancestry JOIN TAXON t USING(taxon_id) ORDER BY ancestry.depth DESC";
    $s=$db->prepare($sql); $s->execute([':id'=>$id]); return $s->fetchAll();
}

function db_children(PDO $db, int $id, int $limit=25): array {
    $s=$db->prepare('SELECT t.*,e.page_no,e.slot_no FROM TAXON_EDGE e JOIN TAXON t ON t.taxon_id=e.child_id WHERE e.parent_id=? ORDER BY e.page_no,e.slot_no LIMIT ?');
    $s->bindValue(1,$id,PDO::PARAM_INT); $s->bindValue(2,min(max($limit,1),ANEMONE_MAX_RESULTS),PDO::PARAM_INT); $s->execute(); return $s->fetchAll();
}

function db_effective_descriptors(PDO $db, int $id, int $limit=250): array {
    $sql="WITH RECURSIVE ancestry(taxon_id,depth) AS (SELECT :id,0 UNION ALL SELECT e.parent_id,ancestry.depth+1 FROM ancestry JOIN TAXON_EDGE e ON e.child_id=ancestry.taxon_id), ranked AS (SELECT d.descriptor_text,td.kind,td.state,td.inheritable,td.confidence,td.source,td.source_ref,a.depth,t.rank AS from_rank,t.canonical_name AS from_name,ROW_NUMBER() OVER (PARTITION BY td.descriptor_id,td.kind ORDER BY a.depth ASC) rn FROM ancestry a JOIN TAXON_DESCRIPTOR td ON td.taxon_id=a.taxon_id JOIN DESCRIPTOR d ON d.descriptor_id=td.descriptor_id JOIN TAXON t ON t.taxon_id=a.taxon_id WHERE a.depth=0 OR td.inheritable=1) SELECT * FROM ranked WHERE rn=1 ORDER BY kind,state,descriptor_text LIMIT :limit";
    $s=$db->prepare($sql); $s->bindValue(':id',$id,PDO::PARAM_INT); $s->bindValue(':limit',min(max($limit,1),1000),PDO::PARAM_INT); $s->execute(); return $s->fetchAll();
}

function taxon_payload(?PDO $db, int $id): ?array {
    if ($db) {
        $taxon=db_taxon($db,$id); if (!$taxon) return null;
        return ['taxon'=>$taxon,'lineage'=>db_lineage($db,$id),'children'=>db_children($db,$id),'descriptors'=>db_effective_descriptors($db,$id)];
    }
    $taxa=demo_taxa(); if (!isset($taxa[$id])) return null;
    return ['taxon'=>$taxa[$id],'lineage'=>demo_lineage($id),'children'=>demo_children($id),'descriptors'=>demo_descriptors($id)];
}

function variants(string $term): array {
    $term=trim(mb_strtolower($term)); if ($term==='') return [];
    $out=[$term];
    if (str_ends_with($term,'ies') && mb_strlen($term)>4) $out[]=mb_substr($term,0,-3).'y';
    elseif (str_ends_with($term,'s') && !str_ends_with($term,'ss')) $out[]=mb_substr($term,0,-1);
    else $out[]=$term.'s';
    return array_values(array_unique($out));
}

function search_taxa(?PDO $db, string $q, int $limit=20): array {
    $q=trim($q); if ($q==='') return [];
    $terms=variants($q);
    if (!$db) {
        $out=[];
        foreach (demo_taxa() as $row) {
            $hay=mb_strtolower(($row['canonical_name']??'').' '.($row['common_name']??''));
            foreach ($terms as $term) if (str_contains($hay,$term)) { $out[]=$row; break; }
        }
        return array_slice($out,0,$limit);
    }
    foreach ($terms as $term) {
        $sql="SELECT DISTINCT t.* FROM TAXON t LEFT JOIN TAXON_ALIAS a ON a.taxon_id=t.taxon_id WHERE lower(t.canonical_name) LIKE :q OR lower(COALESCE(t.common_name,'')) LIKE :q OR lower(COALESCE(t.scientific_name,'')) LIKE :q OR lower(COALESCE(a.alias,'')) LIKE :q ORDER BY CASE WHEN lower(t.canonical_name)=:exact OR lower(COALESCE(t.common_name,''))=:exact THEN 0 ELSE 1 END,length(t.canonical_name),t.canonical_name LIMIT :limit";
        $s=$db->prepare($sql); $s->bindValue(':q','%'.$term.'%'); $s->bindValue(':exact',$term); $s->bindValue(':limit',min(max($limit,1),ANEMONE_MAX_RESULTS),PDO::PARAM_INT); $s->execute();
        $rows=$s->fetchAll(); if ($rows) return $rows;
    }
    return [];
}

function explicit_subjects(string $prompt): array {
    $p=trim(preg_replace('/\s+/u',' ',$prompt) ?? $prompt); $subjects=[];
    $patterns=[
        '/^(?:what|who)\s+(?:is|are|was|were)\s+(?:an?\s+|the\s+)?(.+?)[?!.]*$/iu',
        '/^(?:tell|teach)\s+me\s+about\s+(.+?)[?!.]*$/iu',
        '/^(?:define|explain|describe)\s+(?:an?\s+|the\s+)?(.+?)[?!.]*$/iu',
        '/^(?:show|find|open)\s+(?:me\s+)?(?:an?\s+|the\s+)?(.+?)[?!.]*$/iu',
    ];
    foreach ($patterns as $pattern) if (preg_match($pattern,$p,$m)) $subjects[]=trim($m[1]);
    if (preg_match_all('/["“](.+?)["”]/u',$p,$m)) foreach ($m[1] as $s) $subjects[]=trim($s);
    foreach ($subjects as &$s) $s=preg_replace('/\s+(?:and|with|that|which)\s+.*$/iu','',$s) ?? $s;
    return array_values(array_unique(array_filter($subjects)));
}

function prompt_mentions_taxon(?PDO $db, string $prompt): ?array {
    if (!$db) {
        $lower=mb_strtolower($prompt); $best=null;
        foreach (demo_taxa() as $row) foreach ([$row['canonical_name']??'',$row['common_name']??''] as $name) {
            if ($name!=='' && str_contains($lower,mb_strtolower($name)) && ($best===null || mb_strlen($name)>mb_strlen($best[1]))) $best=[(int)$row['taxon_id'],$name];
        }
        return $best ? taxon_payload(null,$best[0]) : null;
    }
    $sql="SELECT DISTINCT t.* FROM TAXON t LEFT JOIN TAXON_ALIAS a ON a.taxon_id=t.taxon_id WHERE instr(lower(:prompt),lower(t.canonical_name))>0 OR (t.common_name IS NOT NULL AND instr(lower(:prompt),lower(t.common_name))>0) OR (a.alias IS NOT NULL AND instr(lower(:prompt),lower(a.alias))>0) ORDER BY length(COALESCE(a.alias,'')) DESC,length(COALESCE(t.common_name,'')) DESC,length(t.canonical_name) DESC LIMIT 1";
    $s=$db->prepare($sql); $s->execute([':prompt'=>$prompt]); $row=$s->fetch(); return $row ? taxon_payload($db,(int)$row['taxon_id']) : null;
}

function resolve_taxon(?PDO $db, string $prompt, ?int $preferred): ?array {
    // New explicit question always wins over stale selected UI context.
    foreach (explicit_subjects($prompt) as $subject) {
        $hits=search_taxa($db,$subject,1); if ($hits) return taxon_payload($db,(int)$hits[0]['taxon_id']);
    }
    if ($payload=prompt_mentions_taxon($db,$prompt)) return $payload;

    $stop=['what','when','where','which','who','why','how','does','have','with','from','about','this','that','these','those','there','their','then','than','into','show','tell','give','find','explain'];
    $words=preg_split('/[^\pL\pN_-]+/u',$prompt,-1,PREG_SPLIT_NO_EMPTY) ?: [];
    $words=array_values(array_filter($words,fn($w)=>mb_strlen($w)>=4 && !in_array(mb_strtolower($w),$stop,true)));
    usort($words,fn($a,$b)=>mb_strlen($b)<=>mb_strlen($a));
    foreach (array_slice($words,0,10) as $word) { $hits=search_taxa($db,$word,1); if ($hits) return taxon_payload($db,(int)$hits[0]['taxon_id']); }

    // Selected taxonomy is only fallback context for truly contextual follow-ups.
    if ($preferred!==null && preg_match('/\b(it|its|this|that|these|those|they|them|their|here|same)\b/iu',$prompt)) {
        return taxon_payload($db,$preferred);
    }
    return null;
}

function corpus_search(?PDO $encyclopedia, string $prompt, int $limit=4): array {
    if (!$encyclopedia) return [];
    $subjects=explicit_subjects($prompt);
    $terms=$subjects ?: preg_split('/[^\pL\pN_-]+/u',$prompt,-1,PREG_SPLIT_NO_EMPTY);
    $terms=array_values(array_unique(array_filter(array_map('trim',$terms ?: []),fn($s)=>mb_strlen($s)>=3)));
    foreach ($terms as $term) {
        foreach (variants($term) as $variant) {
            $s=$encyclopedia->prepare('SELECT term,text,source_file FROM ENTRY WHERE lower(term)=:term ORDER BY length(text) DESC LIMIT :limit');
            $s->bindValue(':term',$variant); $s->bindValue(':limit',$limit,PDO::PARAM_INT); $s->execute(); $rows=$s->fetchAll();
            if ($rows) return $rows;
        }
    }
    foreach ($terms as $term) {
        $s=$encyclopedia->prepare('SELECT term,text,source_file FROM ENTRY WHERE lower(term) LIKE :q ORDER BY CASE WHEN lower(term)=:exact THEN 0 ELSE 1 END,length(term) LIMIT :limit');
        $s->bindValue(':q','%'.mb_strtolower($term).'%'); $s->bindValue(':exact',mb_strtolower($term)); $s->bindValue(':limit',$limit,PDO::PARAM_INT); $s->execute(); $rows=$s->fetchAll();
        if ($rows) return $rows;
    }
    return [];
}

function clean_definition(string $text, int $max=1400): string {
    $text=trim(preg_replace('/\s+/u',' ',$text) ?? $text);
    if (mb_strlen($text)>$max) $text=mb_substr($text,0,$max).'…';
    return $text;
}

function states_for(array $descriptors): array {
    $out=['present'=>[],'absent'=>[],'variable'=>[]];
    foreach ($descriptors as $d) { $state=$d['state']??'present'; if (isset($out[$state])) $out[$state][]=$d; }
    return $out;
}

function recognized_requested(?PDO $db, string $prompt, array $effective): array {
    $lower=mb_strtolower($prompt); $out=[];
    foreach ($effective as $d) { $text=mb_strtolower((string)$d['descriptor_text']); if ($text!=='' && str_contains($lower,$text)) $out[$text]=$d; }
    if ($db) {
        $s=$db->prepare('SELECT descriptor_text FROM DESCRIPTOR WHERE instr(lower(:prompt),descriptor_text)>0 ORDER BY length(descriptor_text) DESC LIMIT 20'); $s->execute([':prompt'=>$prompt]);
        foreach ($s->fetchAll() as $r) { $t=$r['descriptor_text']; if (!isset($out[$t])) $out[$t]=['descriptor_text'=>$t,'state'=>'unknown','kind'=>'trait']; }
    }
    return array_values($out);
}

function stream_text(string $text): void {
    $sentences=preg_split('/(?<=[.!?])\s+/u',$text,-1,PREG_SPLIT_NO_EMPTY) ?: [$text];
    foreach ($sentences as $sentence) stream_event('chunk',['text'=>rtrim($sentence).' ']);
}

function stream_answer(?PDO $taxonomy, ?PDO $encyclopedia, string $prompt, ?int $preferred): never {
    stream_start();
    stream_event('status',['label'=>'Searching all knowledge','engine'=>$taxonomy?'sqlite-live':'demo']);

    $payload=resolve_taxon($taxonomy,$prompt,$preferred);
    if ($payload) {
        $taxon=$payload['taxon']; $lineage=$payload['lineage']; $descriptors=$payload['descriptors']; $states=states_for($descriptors); $requested=recognized_requested($taxonomy,$prompt,$descriptors);
        stream_event('context',['taxon'=>$taxon,'lineage'=>$lineage,'children'=>$payload['children']]);
        stream_event('status',['label'=>'Resolving taxonomy and inherited traits']);

        $name=$taxon['canonical_name']; $rank=$taxon['rank']; $lineNames=array_map(fn($r)=>$r['canonical_name'],$lineage); $chunks=[];
        if (mb_strtolower($name)==='aves' || mb_strtolower((string)($taxon['common_name']??''))==='birds') {
            $chunks[]='A bird is an animal in the class Aves. Birds are feather-covered vertebrates with beaks and they reproduce by laying eggs. ';
            $chunks[]='Flight is not universal: many birds fly, while groups such as ostriches, emus, cassowaries, rheas, kiwis, and penguins do not use powered flight in the ordinary way. ';
        } else {
            $chunks[]="{$name} is indexed as {$rank}. ";
        }
        if (count($lineNames)>1) $chunks[]='Its loaded lineage is '.implode(' → ',$lineNames).'. ';
        if ($requested) {
            $parts=[]; foreach (['present','absent','variable','unknown'] as $state) {
                $items=[]; foreach ($requested as $d) if (($d['state']??'unknown')===$state) $items[]=$d['descriptor_text'];
                if ($items) $parts[]=$state.': '.implode(', ',$items);
            }
            if ($parts) $chunks[]='For the descriptors in your question: '.implode('; ',$parts).'. ';
        } else {
            $top=array_slice($states['present'],0,7); if ($top) $chunks[]='Effective descriptors include '.implode(', ',array_map(fn($d)=>$d['descriptor_text'],$top)).'. ';
            if ($states['absent']) $chunks[]='Explicit absences include '.implode(', ',array_map(fn($d)=>$d['descriptor_text'],array_slice($states['absent'],0,3))).'. ';
            if ($states['variable']) $chunks[]='Variable traits include '.implode(', ',array_map(fn($d)=>$d['descriptor_text'],array_slice($states['variable'],0,3))).'. ';
        }
        foreach ($chunks as $chunk) stream_event('chunk',['text'=>$chunk]);
        stream_event('evidence',['descriptors'=>array_slice($descriptors,0,100),'requested'=>$requested,'origin_kind'=>$taxon['origin_kind']??'scientific','source'=>$taxon['source']??null,'source_ref'=>$taxon['source_ref']??null]);
        stream_event('status',['label'=>'Ready']); stream_event('done',['engine'=>$taxonomy?'taxonomy-live':'demo','taxon_id'=>(int)$taxon['taxon_id']]); exit;
    }

    stream_event('status',['label'=>'Searching encyclopedia corpus']);
    $entries=corpus_search($encyclopedia,$prompt,4);
    if ($entries) {
        $first=$entries[0]; $definition=clean_definition((string)$first['text']);
        stream_text($definition);
        stream_event('corpus',['term'=>$first['term'],'source_file'=>$first['source_file'],'matches'=>$entries]);
        stream_event('status',['label'=>'Ready']); stream_event('done',['engine'=>'encyclopedia']); exit;
    }

    stream_text('I could not find that concept in the currently loaded taxonomy or encyclopedia index. You do not need to select a taxonomy first; this means the local knowledge indexes themselves do not contain a match yet.');
    stream_event('status',['label'=>'Ready']); stream_event('done',['engine'=>'no-match']); exit;
}

$taxonomy=open_sqlite($taxonomyPath);
$encyclopedia=open_sqlite($encyclopediaPath);
$op=(string)($_GET['op'] ?? 'bootstrap');

if ($op==='bootstrap') {
    if ($taxonomy) {
        $kingdoms=$taxonomy->query("SELECT * FROM TAXON WHERE rank='kingdom' ORDER BY canonical_name LIMIT 100")->fetchAll();
        $taxa=(int)$taxonomy->query('SELECT COUNT(*) FROM TAXON')->fetchColumn();
        $desc=(int)$taxonomy->query('SELECT COUNT(*) FROM TAXON_DESCRIPTOR')->fetchColumn();
        $pageSize=(int)$taxonomy->query('PRAGMA page_size')->fetchColumn(); $pageCount=(int)$taxonomy->query('PRAGMA page_count')->fetchColumn(); $maxPages=(int)$taxonomy->query('PRAGMA max_page_count')->fetchColumn();
        json_out(['mode'=>'live','knowledge_mode'=>$encyclopedia?'all-knowledge':'taxonomy','kingdoms'=>$kingdoms,'ranks'=>['kingdom','phylum','class','order','family','genus','species','type','name'],'stats'=>['taxa'=>$taxa,'descriptor_assignments'=>$desc,'bytes'=>$pageSize*$pageCount,'max_bytes'=>$pageSize*$maxPages]]);
    }
    $taxa=demo_taxa();
    json_out(['mode'=>'demo','knowledge_mode'=>$encyclopedia?'all-knowledge':'demo-plus-taxonomy','kingdoms'=>array_values(array_filter($taxa,fn($r)=>$r['rank']==='kingdom')),'ranks'=>['kingdom','phylum','class','order','family','genus','species','type','name'],'stats'=>['taxa'=>count($taxa),'descriptor_assignments'=>count(demo_descriptors(-16))+count(demo_descriptors(-17)),'bytes'=>0,'max_bytes'=>35*1024**3]]);
}

if ($op==='taxon') {
    $payload=taxon_payload($taxonomy,(int)($_GET['taxon_id']??0)); if (!$payload) json_out(['error'=>'taxon not found'],404); json_out($payload);
}
if ($op==='children') json_out(['children'=>$taxonomy?db_children($taxonomy,(int)($_GET['taxon_id']??0)):demo_children((int)($_GET['taxon_id']??0))]);
if ($op==='search') json_out(['results'=>search_taxa($taxonomy,mb_substr((string)($_GET['q']??''),0,300),25)]);
if ($op==='compare') {
    $body=read_body(); $payload=taxon_payload($taxonomy,(int)($body['taxon_id']??0)); if (!$payload) json_out(['error'=>'taxon not found'],404);
    $effective=[]; foreach ($payload['descriptors'] as $d) $effective[mb_strtolower($d['descriptor_text'])]=$d;
    $result=['present'=>[],'absent'=>[],'variable'=>[],'unknown'=>[]];
    foreach (array_slice(is_array($body['descriptors']??null)?$body['descriptors']:[],0,30) as $raw) { $text=mb_strtolower(trim((string)$raw)); if ($text==='') continue; $d=$effective[$text]??null; $state=$d['state']??'unknown'; $result[$state][]=['descriptor'=>$text,'evidence'=>$d]; }
    json_out(['taxon'=>$payload['taxon'],'result'=>$result]);
}
if ($op==='ask') {
    $body=read_body(); $prompt=trim((string)($body['prompt']??'')); if ($prompt==='') json_out(['error'=>'prompt required'],400); if (mb_strlen($prompt)>ANEMONE_MAX_PROMPT) $prompt=mb_substr($prompt,0,ANEMONE_MAX_PROMPT);
    $preferred=isset($body['taxon_id']) && $body['taxon_id']!==null ? (int)$body['taxon_id'] : null;
    stream_answer($taxonomy,$encyclopedia,$prompt,$preferred);
}
json_out(['error'=>'unknown operation'],404);
