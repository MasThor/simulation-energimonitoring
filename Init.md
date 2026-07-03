[INLFUX]

Token: apiv3_9MlQmU6Dw_VeuV_twYxN7bEheUMZiNrDfn3_ZNhWKFo4Pb5FPFNZR7k19mekz7heT2m1P4l-fMpOI2kgoJ27NA
HTTP Requests Header: Authorization: Bearer apiv3_9MlQmU6Dw_VeuV_twYxN7bEheUMZiNrDfn3_ZNhWKFo4Pb5FPFNZR7k19mekz7heT2m1P4l-fMpOI2kgoJ27NA


docker run --detach \
  --name influxdb3-explorer \
  --pull always \
  --publish 127.0.0.1:8888:8443 \
  --volume $(pwd)/db:/db:rw \
  --volume $(pwd)/influx-ui/config:/app-root/config:ro \
  --volume $(pwd)/ssl:/etc/nginx/ssl:ro \
  --env SESSION_SECRET_KEY=$SESSION_SECRET \
  --restart unless-stopped \
  influxdata/influxdb3-ui:1.9.0 \
  --mode=admin