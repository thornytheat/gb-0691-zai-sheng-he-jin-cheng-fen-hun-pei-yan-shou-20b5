# 接口

`POST /api/run`：JSON中的csv文本，省略使用样例；或multipart字段file。最大5MB。

`POST /api/m1`至`POST /api/m7`：独立运行到指定模块，JSON结构同运行接口。

`POST /api/m8`：炉次烧损对照与下一炉元素补偿，可用run_id查询参数指定批次。`POST /api/m8/tap`：提交出炉实测CSV（batch,element,tap_mass,unit,tap_assay），同炉同元素同值幂等跳过，异值隔离保留原记录。`GET /api/m8/evidence.csv`：导出对照、补偿依据与隔离记录。

`GET /api/history`：历史批次。`POST /api/review`接收id、revision和decision（通过或退回）。`GET /api/evidence.csv`提供单一证据导出。

结构错误422，版本变化409，文件过大413；错误返回code与message。所有页面可从左侧八个模块入口访问。

`GET /api/runs/<id>`读取指定批次；页面与证据CSV通过run_id查询参数绑定批次，模块导航保留该参数。

JSON请求体必须是对象，数组、标量、null、损坏JSON及错误上传字段返回400，且不运行默认样例。
