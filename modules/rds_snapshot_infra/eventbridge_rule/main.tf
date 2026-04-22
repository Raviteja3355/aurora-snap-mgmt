resource "aws_cloudwatch_event_rule" "rule" {
  name                = var.rule_name
  schedule_expression = var.schedule_expression
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "target" {
  rule      = aws_cloudwatch_event_rule.rule.name
  target_id = var.target_id
  arn       = var.target_lambda_arn
}

resource "aws_lambda_permission" "allow" {
  statement_id  = "AllowEventBridgeInvoke_${var.rule_name}"
  action        = "lambda:InvokeFunction"
  function_name = var.target_lambda_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.rule.arn
}
