<?php declare(strict_types=1);

/* Browser/API adapter for the v3 sharded mmap taxonomy store. */
const ANEMONE_MMAP_MAX_RESULTS = 50;
const ANEMONE_RANK_UNIT = 72057594037927936; // 2^56

$ANEMONE_RANKS = [
    1=>'kingdom',2=>'phylum',3=>'class',4=>'order',5=>'family',
    6=>'genus',7=>'species',8=>'type',9=>'name',
];
$ANEMONE_STORE = getenv('ANEMONE_TAXONOMY_STORE')
    ?: dirname(__DIR__) . '/sqlite_taxonomy/anemone_taxonomy.mmap';

function mmap_json_out($payload, int $status=200): void {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE);
    exit;
}

function mmap_read_body(): array {
    $raw=file_get_contents('php://input') ?: '';
    $data=$raw==='' ? [] : json_decode($raw,true);
    return is_array($data) ? $data : [];
}

function mmap_open(string $path): PDO {
    static $opened=[];
    if (isset($opened[$path])) return $opened[$path];
    if (!is_file($path)) throw new RuntimeException('Missing taxonomy shard: '.$path);
    $db=new PDO('sqlite:'.$path,null,null,[
        PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE=>PDO::FETCH_ASSOC,
    ]);
    $db->exec('PRAGMA query_only=ON');
    $db->exec('PRAGMA busy_timeout=2500');
    $db->exec('PRAGMA mmap_size=4294967296');
    return $opened[$path]=$db;
}

function mmap_rank_from_id(int $taxonId): string {
    global $ANEMONE_RANKS;
    $code=intdiv($taxonId, ANEMONE_RANK_UNIT);
    if (!isset($ANEMONE_RANKS[$code])) throw new InvalidArgumentException('Invalid taxon id rank code');
    return $ANEMONE_RANKS[$code];
}

function mmap_local_from_id(int $taxonId): int {
    $code=intdiv($taxonId, ANEMONE_RANK_UNIT);
    return $taxonId-($code*ANEMONE_RANK_UNIT);
}

function mmap_rank_index(string $rank): int {
    static $r=['kingdom','phylum','class','order','family','genus','species','type','name'];
    $i=array_search($rank,$r,true);
    if ($i===false) throw new InvalidArgumentException('Unknown rank '.$rank);
    return (int)$i;
}

function mmap_rank_file(string $rank): string {
    global $ANEMONE_STORE;
    return $ANEMONE_STORE.'/rank_'.str_pad((string)mmap_rank_index($rank),2,'0',STR_PAD_LEFT).'_'.$rank.'.sqlite3';
}

function mmap_edge_file(string $parentRank,string $childRank): string {
    global $ANEMONE_STORE;
    return $ANEMONE_STORE.'/edge_'.str_pad((string)mmap_rank_index($parentRank),2,'0',STR_PAD_LEFT).'_'.$parentRank.'_'.$childRank.'.sqlite3';
}

function mmap_catalog(): PDO {
    global $ANEMONE_STORE;
    return mmap_open($ANEMONE_STORE.'/catalog.sqlite3');
}

function mmap_catalog_taxon(int $taxonId): ?array {
    $s=mmap_catalog()->prepare('SELECT * FROM TAXON_INDEX WHERE taxon_id=?');
    $s->execute([$taxonId]); $r=$s->fetch(); return $r ?: null;
}

function mmap_rank_taxon(int $taxonId): ?array {
    $rank=mmap_rank_from_id($taxonId); $local=mmap_local_from_id($taxonId);
    $s=mmap_open(mmap_rank_file($rank))->prepare('SELECT * FROM TAXON WHERE local_id=?');
    $s->execute([$local]); $r=$s->fetch();
    if (!$r) return null;
    $r['rank']=$rank;
    return $r;
}

function mmap_lineage(int $taxonId): array {
    $cat=mmap_catalog(); $out=[]; $seen=[]; $id=$taxonId; $depth=0;
    while ($id!==null && !isset($seen[$id]) && $depth<16) {
        $seen[$id]=true;
        $s=$cat->prepare('SELECT * FROM TAXON_INDEX WHERE taxon_id=?'); $s->execute([$id]);
        $row=$s->fetch(); if(!$row) break;
        $row['depth']=$depth; array_unshift($out,$row);
        $id=$row['parent_id']===null ? null : (int)$row['parent_id'];
        $depth++;
    }
    // Normalize depth to target=0, parent=1, etc. for UI provenance.
    $n=count($out);
    foreach($out as $i=>&$row) $row['depth']=$n-1-$i;
    unset($row);
    return $out;
}

function mmap_children(int $parentId,int $limit=25): array {
    $parentRank=mmap_rank_from_id($parentId); $i=mmap_rank_index($parentRank);
    $ranks=['kingdom','phylum','class','order','family','genus','species','type','name'];
    if ($i>=count($ranks)-1) return [];
    $childRank=$ranks[$i+1];
    $edb=mmap_open(mmap_edge_file($parentRank,$childRank));
    $s=$edb->prepare('SELECT child_id,page_no,slot_no FROM EDGE WHERE parent_id=? ORDER BY page_no,slot_no LIMIT ?');
    $s->bindValue(1,$parentId,PDO::PARAM_INT); $s->bindValue(2,max(1,min($limit,ANEMONE_MMAP_MAX_RESULTS)),PDO::PARAM_INT); $s->execute();
    $edges=$s->fetchAll(); if(!$edges) return [];
    $cat=mmap_catalog(); $out=[];
    $q=$cat->prepare('SELECT * FROM TAXON_INDEX WHERE taxon_id=?');
    foreach($edges as $edge) {
        $q->execute([(int)$edge['child_id']]); $row=$q->fetch(); if(!$row) continue;
        $row['page_no']=(int)$edge['page_no']; $row['slot_no']=(int)$edge['slot_no']; $out[]=$row;
    }
    return $out;
}

function mmap_effective_descriptors(int $taxonId): array {
    $rank=mmap_rank_from_id($taxonId);
    if ($rank==='kingdom') {
        $local=mmap_local_from_id($taxonId);
        $s=mmap_open(mmap_rank_file($rank))->prepare(
            "SELECT descriptor_text,kind,state,inheritable,confidence,novelty_score,source,source_ref FROM LOCAL_DESCRIPTOR WHERE local_id=? ORDER BY kind,state,descriptor_text"
        );
        $s->execute([$local]); $rows=$s->fetchAll();
        foreach($rows as &$r){$r['depth']=0;$r['from_rank']='kingdom';$r['from_name']=(mmap_catalog_taxon($taxonId)['canonical_name']??'kingdom');}
        unset($r); return $rows;
    }
    $ranks=['kingdom','phylum','class','order','family','genus','species','type','name'];
    $i=mmap_rank_index($rank); $parentRank=$ranks[$i-1];
    $db=mmap_open(mmap_edge_file($parentRank,$rank));
    $s=$db->prepare(
        "SELECT constraint_key AS descriptor_text,constraint_type AS kind,state,inheritable,confidence,novelty_score,origin_taxon_id,source,source_ref FROM CHILD_CONSTRAINT WHERE child_id=? AND constraint_type IN ('trait','phenotype') ORDER BY constraint_type,state,constraint_key"
    );
    $s->execute([$taxonId]); $rows=$s->fetchAll(); if(!$rows) return [];
    $line=mmap_lineage($taxonId); $depthBy=[]; foreach($line as $lr)$depthBy[(int)$lr['taxon_id']]=(int)$lr['depth'];
    $origins=[]; foreach($rows as $r)$origins[(int)$r['origin_taxon_id']]=true;
    $originRows=[]; foreach(array_keys($origins) as $oid){$or=mmap_catalog_taxon((int)$oid);if($or)$originRows[(int)$oid]=$or;}
    foreach($rows as &$r){
        $oid=(int)$r['origin_taxon_id']; $r['depth']=$depthBy[$oid]??0;
        $r['from_rank']=$originRows[$oid]['rank']??null; $r['from_name']=$originRows[$oid]['canonical_name']??null;
        unset($r['origin_taxon_id']);
    }
    unset($r); return $rows;
}

function mmap_taxon_payload(int $taxonId): ?array {
    $taxon=mmap_catalog_taxon($taxonId); if(!$taxon) return null;
    return ['taxon'=>$taxon,'lineage'=>mmap_lineage($taxonId),'children'=>mmap_children($taxonId),'descriptors'=>mmap_effective_descriptors($taxonId)];
}

function mmap_search(string $q,int $limit=20): array {
    $q=trim($q); if($q==='') return [];
    $limit=max(1,min($limit,ANEMONE_MMAP_MAX_RESULTS)); $cat=mmap_catalog(); $lower=strtolower($q);
    $sql="SELECT * FROM TAXON_INDEX WHERE lower(canonical_name)=:exact OR lower(COALESCE(common_name,''))=:exact OR lower(COALESCE(scientific_name,''))=:exact OR lower(canonical_name) LIKE :prefix OR lower(COALESCE(common_name,'')) LIKE :prefix OR lower(COALESCE(scientific_name,'')) LIKE :prefix OR lower(canonical_name) LIKE :contains OR lower(COALESCE(common_name,'')) LIKE :contains ORDER BY CASE WHEN lower(canonical_name)=:exact OR lower(COALESCE(common_name,''))=:exact THEN 0 WHEN lower(canonical_name) LIKE :prefix THEN 1 ELSE 2 END,length(canonical_name),canonical_name LIMIT :limit";
    $s=$cat->prepare($sql); $s->bindValue(':exact',$lower);$s->bindValue(':prefix',$lower.'%');$s->bindValue(':contains','%'.$lower.'%');$s->bindValue(':limit',$limit,PDO::PARAM_INT);$s->execute();
    return $s->fetchAll();
}

function mmap_compare(int $taxonId,array $requested): array {
    $effective=[]; foreach(mmap_effective_descriptors($taxonId) as $d)$effective[strtolower(trim($d['descriptor_text']))]=$d;
    $out=['present'=>[],'absent'=>[],'variable'=>[],'unknown'=>[]];
    foreach($requested as $raw){
        $text=strtolower(trim(preg_replace('/\s+/',' ',(string)$raw)));
        if($text==='')continue; $d=$effective[$text]??null; $state=$d['state']??'unknown';
        if(!isset($out[$state]))$state='unknown'; $out[$state][]=['descriptor'=>$text,'kind'=>$d['kind']??'trait'];
    }
    return $out;
}

function mmap_bootstrap(): array {
    global $ANEMONE_STORE;
    $cat=mmap_catalog(); $taxa=(int)$cat->query('SELECT COUNT(*) FROM TAXON_INDEX')->fetchColumn();
    $bytes=0; foreach(glob($ANEMONE_STORE.'/*.sqlite3')?:[] as $f)$bytes+=filesize($f)?:0;
    $kingdoms=$cat->query("SELECT * FROM TAXON_INDEX WHERE rank='kingdom' ORDER BY canonical_name LIMIT 50")->fetchAll();
    $descriptors=0;
    $ranks=['kingdom','phylum','class','order','family','genus','species','type','name'];
    for($i=0;$i<count($ranks)-1;$i++){
        $p=mmap_edge_file($ranks[$i],$ranks[$i+1]); if(!is_file($p))continue;
        $db=mmap_open($p); $descriptors+=(int)$db->query("SELECT COUNT(*) FROM CHILD_CONSTRAINT WHERE constraint_type IN ('trait','phenotype')")->fetchColumn();
    }
    return ['mode'=>'mmap','engine'=>'sharded-mmap-v3','kingdoms'=>$kingdoms,'ranks'=>$ranks,'taxa'=>$taxa,'descriptor_assignments'=>$descriptors,'main_bytes'=>$bytes,'max_bytes'=>0,'store_path'=>$ANEMONE_STORE];
}

$op=(string)($_GET['op']??'bootstrap');
try {
    if($op==='bootstrap') mmap_json_out(mmap_bootstrap());
    if($op==='search') mmap_json_out(['results'=>mmap_search((string)($_GET['q']??''))]);
    if($op==='taxon'){
        $id=(int)($_GET['taxon_id']??0); $p=mmap_taxon_payload($id); if(!$p)mmap_json_out(['error'=>'taxon not found'],404); mmap_json_out($p);
    }
    if($op==='children'){
        $id=(int)($_GET['taxon_id']??0); mmap_json_out(['children'=>mmap_children($id)]);
    }
    if($op==='compare'){
        $body=mmap_read_body(); $id=(int)($body['taxon_id']??0); $requested=is_array($body['descriptors']??null)?$body['descriptors']:[];
        $taxon=mmap_catalog_taxon($id); if(!$taxon)mmap_json_out(['error'=>'taxon not found'],404);
        mmap_json_out(['taxon'=>$taxon,'result'=>mmap_compare($id,$requested)]);
    }
    mmap_json_out(['error'=>'unknown operation'],404);
} catch(Throwable $e) {
    mmap_json_out(['error'=>$e->getMessage(),'engine'=>'sharded-mmap-v3'],500);
}
