<?php declare(strict_types=1);

/* Browser adapter for Anemone taxonomy v3 shard store. */
const MMAP_RANK_UNIT = 562949953421312; // 2^49, keeps ids < 2^53
const MMAP_MAX_RESULTS = 50;

$MMAP_RANKS = [
    1=>'kingdom',2=>'phylum',3=>'class',4=>'order',5=>'family',
    6=>'genus',7=>'species',8=>'type',9=>'name',
];
$MMAP_STORE = getenv('ANEMONE_TAXONOMY_STORE')
    ?: dirname(__DIR__) . '/sqlite_taxonomy/anemone_taxonomy.mmap';

function v3_json($payload,int $status=200): void {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($payload,JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE);
    exit;
}
function v3_body(): array {
    $raw=file_get_contents('php://input') ?: '';
    $v=$raw===''?[]:json_decode($raw,true);
    return is_array($v)?$v:[];
}
function v3_db(string $path): PDO {
    static $db=[];
    if(isset($db[$path])) return $db[$path];
    if(!is_file($path)) throw new RuntimeException('Missing taxonomy shard: '.$path);
    $p=new PDO('sqlite:'.$path,null,null,[PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION,PDO::ATTR_DEFAULT_FETCH_MODE=>PDO::FETCH_ASSOC]);
    $p->exec('PRAGMA query_only=ON');
    $p->exec('PRAGMA busy_timeout=2500');
    $p->exec('PRAGMA mmap_size=4294967296');
    return $db[$path]=$p;
}
function v3_rank(int $id): string {
    global $MMAP_RANKS;
    $code=intdiv($id,MMAP_RANK_UNIT);
    if(!isset($MMAP_RANKS[$code])) throw new InvalidArgumentException('Invalid taxon id');
    return $MMAP_RANKS[$code];
}
function v3_local(int $id): int { $c=intdiv($id,MMAP_RANK_UNIT); return $id-($c*MMAP_RANK_UNIT); }
function v3_ri(string $rank): int {
    static $r=['kingdom','phylum','class','order','family','genus','species','type','name'];
    $i=array_search($rank,$r,true); if($i===false) throw new InvalidArgumentException('Unknown rank'); return (int)$i;
}
function v3_rank_path(string $rank): string {
    global $MMAP_STORE; return $MMAP_STORE.'/rank_'.str_pad((string)v3_ri($rank),2,'0',STR_PAD_LEFT).'_'.$rank.'.sqlite3';
}
function v3_edge_path(string $p,string $c): string {
    global $MMAP_STORE; return $MMAP_STORE.'/edge_'.str_pad((string)v3_ri($p),2,'0',STR_PAD_LEFT).'_'.$p.'_'.$c.'.sqlite3';
}
function v3_cat(): PDO { global $MMAP_STORE; return v3_db($MMAP_STORE.'/catalog.sqlite3'); }
function v3_taxon(int $id): ?array {
    $s=v3_cat()->prepare('SELECT * FROM TAXON_INDEX WHERE taxon_id=?'); $s->execute([$id]); $r=$s->fetch(); return $r?:null;
}
function v3_lineage(int $id): array {
    $out=[];$seen=[];$cat=v3_cat();$cur=$id;$guard=0;
    while($cur!==null&&!isset($seen[$cur])&&$guard++<16){
        $seen[$cur]=1;$s=$cat->prepare('SELECT * FROM TAXON_INDEX WHERE taxon_id=?');$s->execute([$cur]);$r=$s->fetch();if(!$r)break;
        array_unshift($out,$r);$cur=$r['parent_id']===null?null:(int)$r['parent_id'];
    }
    $n=count($out);foreach($out as $i=>&$r)$r['depth']=$n-1-$i;unset($r);return $out;
}
function v3_children(int $id,int $limit=25): array {
    static $r=['kingdom','phylum','class','order','family','genus','species','type','name'];
    $pr=v3_rank($id);$i=v3_ri($pr);if($i>=8)return[];$cr=$r[$i+1];
    $db=v3_db(v3_edge_path($pr,$cr));$s=$db->prepare('SELECT child_id,page_no,slot_no FROM EDGE WHERE parent_id=? ORDER BY page_no,slot_no LIMIT ?');
    $s->bindValue(1,$id,PDO::PARAM_INT);$s->bindValue(2,max(1,min($limit,MMAP_MAX_RESULTS)),PDO::PARAM_INT);$s->execute();$out=[];
    foreach($s->fetchAll() as $e){$t=v3_taxon((int)$e['child_id']);if(!$t)continue;$t['page_no']=(int)$e['page_no'];$t['slot_no']=(int)$e['slot_no'];$out[]=$t;}return$out;
}
function v3_descriptors(int $id): array {
    $rank=v3_rank($id);
    if($rank==='kingdom'){
        $db=v3_db(v3_rank_path($rank));$s=$db->prepare('SELECT descriptor_text,kind,state,inheritable,confidence,novelty_score,source,source_ref FROM LOCAL_DESCRIPTOR WHERE local_id=? ORDER BY kind,state,descriptor_text');$s->execute([v3_local($id)]);$rows=$s->fetchAll();$t=v3_taxon($id);
        foreach($rows as &$x){$x['depth']=0;$x['from_rank']='kingdom';$x['from_name']=$t['canonical_name']??'kingdom';}unset($x);return$rows;
    }
    static $r=['kingdom','phylum','class','order','family','genus','species','type','name'];$i=v3_ri($rank);$pr=$r[$i-1];
    $db=v3_db(v3_edge_path($pr,$rank));$s=$db->prepare("SELECT constraint_key descriptor_text,constraint_type kind,state,inheritable,confidence,novelty_score,origin_taxon_id,source,source_ref FROM CHILD_CONSTRAINT WHERE child_id=? AND constraint_type IN ('trait','phenotype') ORDER BY constraint_type,state,constraint_key");$s->execute([$id]);$rows=$s->fetchAll();
    $line=v3_lineage($id);$depth=[];foreach($line as $x)$depth[(int)$x['taxon_id']]=(int)$x['depth'];
    foreach($rows as &$x){$o=v3_taxon((int)$x['origin_taxon_id']);$x['depth']=$depth[(int)$x['origin_taxon_id']]??0;$x['from_rank']=$o['rank']??null;$x['from_name']=$o['canonical_name']??null;unset($x['origin_taxon_id']);}unset($x);return$rows;
}
function v3_payload(int $id): ?array { $t=v3_taxon($id);return$t?['taxon'=>$t,'lineage'=>v3_lineage($id),'children'=>v3_children($id),'descriptors'=>v3_descriptors($id)]:null; }
function v3_search(string $q,int $limit=20): array {
    $q=trim(strtolower($q));if($q==='')return[];$s=v3_cat()->prepare("SELECT * FROM TAXON_INDEX WHERE lower(canonical_name)=:e OR lower(COALESCE(common_name,''))=:e OR lower(COALESCE(scientific_name,''))=:e OR lower(canonical_name) LIKE :p OR lower(COALESCE(common_name,'')) LIKE :p OR lower(COALESCE(scientific_name,'')) LIKE :p OR lower(canonical_name) LIKE :c OR lower(COALESCE(common_name,'')) LIKE :c ORDER BY CASE WHEN lower(canonical_name)=:e OR lower(COALESCE(common_name,''))=:e THEN 0 WHEN lower(canonical_name) LIKE :p THEN 1 ELSE 2 END,length(canonical_name),canonical_name LIMIT :l");
    $s->bindValue(':e',$q);$s->bindValue(':p',$q.'%');$s->bindValue(':c','%'.$q.'%');$s->bindValue(':l',max(1,min($limit,MMAP_MAX_RESULTS)),PDO::PARAM_INT);$s->execute();return$s->fetchAll();
}
function v3_compare(int $id,array $requested): array {
    $map=[];foreach(v3_descriptors($id) as $d)$map[strtolower(trim($d['descriptor_text']))]=$d;$out=['present'=>[],'absent'=>[],'variable'=>[],'unknown'=>[]];
    foreach($requested as $raw){$t=strtolower(trim(preg_replace('/\s+/',' ',(string)$raw)));if($t==='')continue;$d=$map[$t]??null;$st=$d['state']??'unknown';if(!isset($out[$st]))$st='unknown';$out[$st][]=['descriptor'=>$t,'kind'=>$d['kind']??'trait'];}return$out;
}
function v3_bootstrap(): array {
    global $MMAP_STORE;$cat=v3_cat();$taxa=(int)$cat->query('SELECT COUNT(*) FROM TAXON_INDEX')->fetchColumn();$kingdoms=$cat->query("SELECT * FROM TAXON_INDEX WHERE rank='kingdom' ORDER BY canonical_name LIMIT 50")->fetchAll();
    $bytes=0;foreach(glob($MMAP_STORE.'/*.sqlite3')?:[] as $f)$bytes+=(int)(filesize($f)?:0);$manifest=[];$mp=$MMAP_STORE.'/store.json';if(is_file($mp)){$manifest=json_decode((string)file_get_contents($mp),true)?:[];}$max=(int)(($manifest['budget_gib']??35)*1024*1024*1024);
    $desc=0;$r=['kingdom','phylum','class','order','family','genus','species','type','name'];for($i=0;$i<8;$i++){$p=v3_edge_path($r[$i],$r[$i+1]);if(is_file($p))$desc+=(int)v3_db($p)->query("SELECT COUNT(*) FROM CHILD_CONSTRAINT WHERE constraint_type IN ('trait','phenotype')")->fetchColumn();}
    return ['mode'=>'live','engine'=>'sharded-mmap-v3','kingdoms'=>$kingdoms,'ranks'=>$r,'stats'=>['taxa'=>$taxa,'descriptor_assignments'=>$desc,'bytes'=>$bytes,'max_bytes'=>$max],'store_path'=>$MMAP_STORE];
}

$op=(string)($_GET['op']??'bootstrap');
try{
    if($op==='bootstrap')v3_json(v3_bootstrap());
    if($op==='search')v3_json(['results'=>v3_search((string)($_GET['q']??''))]);
    if($op==='taxon'){$id=(int)($_GET['taxon_id']??0);$p=v3_payload($id);if(!$p)v3_json(['error'=>'taxon not found'],404);v3_json($p);}
    if($op==='children'){$id=(int)($_GET['taxon_id']??0);v3_json(['children'=>v3_children($id)]);}
    if($op==='compare'){$b=v3_body();$id=(int)($b['taxon_id']??0);$t=v3_taxon($id);if(!$t)v3_json(['error'=>'taxon not found'],404);v3_json(['taxon'=>$t,'result'=>v3_compare($id,is_array($b['descriptors']??null)?$b['descriptors']:[])]);}
    v3_json(['error'=>'unknown operation'],404);
}catch(Throwable $e){v3_json(['error'=>$e->getMessage(),'engine'=>'sharded-mmap-v3'],500);}
