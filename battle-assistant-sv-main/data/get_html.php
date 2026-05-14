<?PHP
    $url = $argv[1];
    $fname = "/home/pbasv/pbasv.cloudfree.jp/public_html/data/log/result.html";
    $fp = fopen($fname, "w");
    $options = [
        'http' => [
            'method' => 'GET',
            'header' => 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36',
        ],
    ];
    $context = stream_context_create($options);
    fwrite($fp, file_get_contents($url,false,$context));
    fclose($fp);
?>